"""
PyProvide - Barebones dependency injection framework for Python, based on type hints.

For usage, see README.md.

Licensed under the MIT License. For details, see the LICENSE file.

Author: Jake Hartz <jake@hartz.io>
"""

import inspect
from typing import \
    Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple, TypeVar, Union, \
    cast, get_type_hints

InjectableClassType = TypeVar("InjectableClassType")

# Used as the return type for class providers, like: .... -> InjectableClass[ReturnedClass]
InjectableClass = Callable[..., InjectableClassType]

# Represents an __init__ method of a class
_InitMethod = Callable[..., None]

# The name of an attribute that is set on methods decorated with one of our decorator functions
_PYPROVIDE_PROPERTIES_ATTR = "_pyprovide_properties"


###################################################################################################
# Exceptions
###################################################################################################


class BadProviderError(Exception):
    """
    Raised when an invalid provider function is decorated with "@provider()" or "@class_provider()"
    in a module.
    """


class BadModuleError(Exception):
    """
    Raised when an invalid module is passed to another module's "install" method or used as an
    argument to Injector's __init__ method.
    """


class DependencyError(Exception):
    """
    Raised when the injector has an issue providing a dependency.
    """
    def __init__(self, reason: str, dependency_chain: List[type], name: Optional[str] = None) -> \
            None:
        self.reason = reason
        self.dependency_chain = dependency_chain
        self.name = name

    def __str__(self) -> str:
        err = self.reason
        if self.name is not None:
            err += " (\"%s\")" % self.name
        err += ": " + ", required by".join(str(d) for d in self.dependency_chain)
        return err


###################################################################################################
# "Properties" named tuples (attached to methods decorated with one of our decorator functions)
###################################################################################################


class _InjectDecoratorProperties(NamedTuple):
    # Properties attached to a method decorated with "@inject(...)"
    named_dependencies: Dict[str, str]


class _ProviderDecoratorProperties(NamedTuple):
    # Properties attached to a method decorated with "@provider(...)" or "@class_provider(...)"
    named_dependencies: Dict[str, str]
    provided_dependency_type: type
    provided_dependency_name: Optional[str]
    is_class_provider: bool


###################################################################################################
# Classes/functions related to providers
###################################################################################################


class _ProviderKey:
    """
    A key for a provider for a dependency, including the provided type and name (if it's for a
    named dependency). This is used to ensure uniqueness of providers in a module or injector's
    registry.
    """
    def __init__(self, provided_dependency_type: type, provided_dependency_name: Optional[str],
                 provider_method_name: Optional[str] = None,
                 containing_module: Optional["Module"] = None) -> None:
        self.provided_dependency_type = provided_dependency_type
        self.provided_dependency_name = provided_dependency_name

        # Only used for error messages; not included in equality checks or hashing.
        # These aren't provided when we are constructing a ProviderKey just to do a lookup.
        self.provider_method_name = provider_method_name
        self.containing_module = containing_module

    def __hash__(self) -> int:
        return hash((self.provided_dependency_type, self.provided_dependency_name))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _ProviderKey):
            raise NotImplemented
        return (self.provided_dependency_type == other.provided_dependency_type) and \
               (self.provided_dependency_name == other.provided_dependency_name)

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, _ProviderKey):
            raise NotImplemented
        return not self.__eq__(other)

    def __str__(self) -> str:
        props = ["Provider"]

        if self.provider_method_name is not None:
            props.append(self.provider_method_name)
        if self.containing_module is not None:
            props.append("in %s" % self.containing_module)

        props.append("for %s" % self.provided_dependency_type)
        if self.provided_dependency_name is not None:
            props.append("(named %s)" % self.provided_dependency_name)

        return " ".join(props)

    def __repr__(self) -> str:
        if self.provided_dependency_name is not None:
            return "_ProviderKey(%s, name=%s)" % (repr(self.provided_dependency_type),
                                                  repr(self.provided_dependency_name))
        else:
            return "_ProviderKey(%s)" % repr(self.provided_dependency_type)

_ProviderMethod = Callable[..., Any]


def _is_decorated_class(dependency: type) -> bool:
    # To make the type checker happy (it doesn't like when we access "__init__" directly)
    dependency_unsafe: Any = dependency
    if not hasattr(dependency_unsafe.__init__, _PYPROVIDE_PROPERTIES_ATTR):
        return False
    properties = getattr(dependency_unsafe.__init__, _PYPROVIDE_PROPERTIES_ATTR)
    return isinstance(properties, _InjectDecoratorProperties)


KEY_TYPE = TypeVar("KEY_TYPE")


def _get_matching_dict_key(d: Dict[KEY_TYPE, Any], k: KEY_TYPE) -> Tuple[KEY_TYPE, KEY_TYPE]:
    """
    Searches a dictionary for a key, and returns a tuple (key1, key2) containing both the key we
    used when searching and the key actually in the dictionary.

    To accomplish this, it iterates through all the items in the dictionary, so be sure to do a
    "key in dict" check before calling this.
    """
    for key in d:
        if key == k:
            return k, key
    raise ValueError("%s not in %s" % (k, d))


def _get_param_names_and_hints(func: Callable[..., Any], skip_params: int = 0) -> \
        Iterable[Tuple[str, Any]]:
    param_names = list(inspect.signature(func).parameters.keys())[skip_params:]
    type_hints = get_type_hints(func)
    return ((p, type_hints.get(p)) for p in param_names)


###################################################################################################
# Public classes
###################################################################################################


class Module:
    def __init__(self) -> None:
        self._providers: Dict[_ProviderKey, _ProviderMethod] = {}
        self._sub_modules: List[Module] = []

        # Register all the providers in this class
        # (requires iterating over all of this class's members, and letting "_register" filter out
        # any that don't have one of our decorators)
        for name, func in inspect.getmembers(self):
            self._register(func, name)

    def _register(self, provider_method: _ProviderMethod, provider_method_name: str) -> None:
        if not hasattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR):
            # This method isn't decorated with one of our decorators; it's probably just a normal
            # helper method in the module class
            return

        properties = getattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR)
        if not isinstance(properties, _ProviderDecoratorProperties):
            raise BadProviderError("%s is decorated with an invalid decorator; use @provider() or "
                                   "@class_provider() to register providers in modules." %
                                   provider_method_name)

        provider_key = _ProviderKey(properties.provided_dependency_type,
                                    properties.provided_dependency_name,
                                    provider_method_name, self)
        if provider_key in self._providers:
            raise BadProviderError("Found colliding providers: %s and %s" %
                                   _get_matching_dict_key(self._providers, provider_key))
        self._providers[provider_key] = provider_method

    def install(self, *modules: "Module") -> None:
        self._sub_modules += modules


class Injector:
    def __init__(self, *modules: Module) -> None:
        self._provider_registry: Dict[_ProviderKey, _ProviderMethod] = {}
        self._added_modules: Set[Module] = set()

        duplicate_pairs = self._add_modules(modules)
        if len(duplicate_pairs) > 0:
            raise BadModuleError("Found duplicate providers: " +
                                 "; ".join("%s and %s" % (p1, p2) for p1, p2 in duplicate_pairs))

    def _add_modules(self, modules: Iterable["Module"]) -> List[Tuple[_ProviderKey, _ProviderKey]]:
        """
        Add modules, returning a list containing any duplicate providers found while adding them.
        """
        duplicate_pairs: List[Tuple[_ProviderKey, _ProviderKey]] = []
        for m in modules:
            if m in self._added_modules:
                continue
            self._added_modules.add(m)
            for provider_key in m._providers:
                if provider_key in self._provider_registry:
                    duplicate_pairs.append(_get_matching_dict_key(self._provider_registry,
                                                                  provider_key))
                else:
                    self._provider_registry[provider_key] = m._providers[provider_key]
            duplicate_pairs += self._add_modules(m._sub_modules)
        return duplicate_pairs

    def get_instance(self, dependency: type, dependency_name: Optional[str] = None) -> Any:
        """
        Get an instance of an injectable class.

        :param dependency: The class that we will return an instance of.
        :param dependency_name: The name of the dependency, if we want a named dependency.
        """
        return self._resolve(dependency, dependency_name)

    def _resolve(self, dependency: type, dependency_name: Optional[str] = None,
                 dependency_chain: Optional[List[type]] = None) -> Any:
        """
        Find or create a provider for a dependency, and call it to get an instance of the
        dependency, returning the result.
        """
        if not dependency_chain:
            dependency_chain = []
        dependency_chain = [dependency] + dependency_chain
        if not isinstance(dependency, type):
            raise DependencyError("Dependency is not a type", dependency_chain, dependency_name)

        # Try to find a provider for the dependency
        provider_key = _ProviderKey(dependency, dependency_name)
        provider_method: Optional[_ProviderMethod] = None
        try:
            provider_method = self._provider_registry[provider_key]
        except KeyError:
            pass

        method_or_class: Union[_ProviderMethod, type, None] = None
        if provider_method is not None:
            method_or_class = provider_method
        else:
            # We don't have a provider; but if the class is a decorated class, we can pass in the
            # class itself (unless they want a named dependency).
            # This is, essentially, the concept of the "default provider"
            if not dependency_name and _is_decorated_class(dependency):
                method_or_class = dependency

        if not method_or_class:
            raise DependencyError("Could not find or create provider for dependency",
                                  dependency_chain, dependency_name)

        return self._call_with_dependencies(method_or_class, dependency_chain)

    def _call_with_dependencies(self, method_or_class: Union[_ProviderMethod, type],
                                dependency_chain: List[type]) -> Any:
        """
        Get instances of a decorated class's or a provider method's dependencies, and then call the
        method or instantiate the class, returning the result.

        :param method_or_class: Either a decorated class, or a provider method.
        :param dependency_chain: The chain of dependencies that got us to this one (used for error
            messages).
        """
        if not callable(method_or_class):
            raise ValueError("Argument is not a function or a class: %s" % method_or_class)

        def result_handler(result: Any) -> Any:
            return result

        if inspect.isclass(method_or_class):
            # It's a class (better be a decorated class)
            # To make the type checker happy (it doesn't like when we access "__init__" directly)
            class_unsafe: Any = method_or_class
            params = _get_param_names_and_hints(class_unsafe.__init__, skip_params=1)
            properties = getattr(class_unsafe.__init__, _PYPROVIDE_PROPERTIES_ATTR)
        else:
            # It's a function (better be a provider method)
            provider_method: _ProviderMethod = cast(_ProviderMethod, method_or_class)
            params = _get_param_names_and_hints(provider_method)
            properties = getattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR)

            if properties.is_class_provider:
                # Handle a class provider's return value
                def result_handler(result: Any) -> Any:
                    if not isinstance(result, type):
                        raise DependencyError("Class provider \"%s\" returned a non-type" %
                                              method_or_class.__name__, dependency_chain)
                    if not _is_decorated_class(result):
                        raise DependencyError("Class provider \"%s\" returned a non-decorated "
                                              "class" % method_or_class.__name__, dependency_chain)
                    return self._call_with_dependencies(result, dependency_chain)

        args = []
        for param_name, type_hint in params:
            if not type_hint:
                raise DependencyError("Dependency parameter \"%s\" in \"%s\" missing type hint" %
                                      (param_name, method_or_class.__name__), dependency_chain)
            args.append(self._resolve(type_hint,
                                      properties.named_dependencies.get(param_name),
                                      dependency_chain))
        return result_handler(method_or_class(*args))


###################################################################################################
# Decorator functions
###################################################################################################


def inject(**named_dependencies: str) -> Callable[[_InitMethod], _InitMethod]:
    """
    Decorator for a class's __init__ method that uses the method's parameters to inject the class's
    dependencies. The type of each parameter is determined by the parameter's type hint annotation.
    This type is used as the key in the injector's registry to find a provider for the dependency.

    Dependencies can also be named; this is specified by passing the name of the dependency as a
    keyword argument to the call to inject(), like so: @inject(parameter_name="dependency name")
    For more, see the README file.

    This decorator does not change the behavior of the method, but it marks it as being able to
    have its parameters injected, and, if named dependencies are used, it records that information
    for future use by the injector.

    Note that you must call this decorator like a function (i.e. like "@inject()" or
    "@inject( ... )", NOT just "@inject").
    """
    def handle(func: _InitMethod) -> _InitMethod:
        setattr(func, _PYPROVIDE_PROPERTIES_ATTR, _InjectDecoratorProperties(named_dependencies))
        return func
    return handle


def _get_provider_return_type(provider_method: _ProviderMethod, provider_type: str) -> type:
    signature = inspect.signature(provider_method)

    # Validate the return type annotation
    return_type = signature.return_annotation
    if return_type is inspect.Signature.empty:
        raise BadProviderError("%s \"%s\" missing return type annotation" %
                               (provider_type, provider_method.__name__))
    if not isinstance(return_type, type):
        raise BadProviderError("%s \"%s\" return type annotation \"%s\" is not a type" %
                               (provider_type, provider_method.__name__, return_type))

    # Validate that all the arguments have type hints
    for param_name, type_hint in _get_param_names_and_hints(provider_method, skip_params=1):
        if not type_hint:
            raise BadProviderError("%s \"%s\" missing type hint annotation for parameter \"%s\"" %
                                   (provider_type, provider_method.__name__, param_name))
        if not isinstance(type_hint, type):
            raise BadProviderError("%s \"%s\" annotation for parameter \"%s\" is not a type" %
                                   (provider_type, provider_method.__name__, param_name))

    return return_type


def provider(provided_dependency_name: Optional[str] = None, **named_dependencies: str) -> \
        Callable[[_ProviderMethod], _ProviderMethod]:
    """
    Method decorator for instance provider methods in a module class. The provider method can take
    parameters representing dependencies, just like the "@inject()" decorator, and named
    dependencies can be specified in the call to "@provider(...)". For details on how this works,
    see the "inject" function's documentation, or look at the README file.

    This decorator does not change the behavior of the method, but it marks it as being a provider
    (and also stores this in its parent class).

    Note that you must call this decorator like a function (i.e. like "@provider()" or
    "@provider( ... )", NOT just "@provider").
    """
    def handle(provider_method: _ProviderMethod) -> _ProviderMethod:
        provided_dependency_type = _get_provider_return_type(provider_method, "Provider")
        setattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR,
                _ProviderDecoratorProperties(named_dependencies,
                                             provided_dependency_type,
                                             provided_dependency_name,
                                             False))
        return provider_method
    return handle


def class_provider(provided_dependency_name: Optional[str] = None, **named_dependencies: str) -> \
        Callable[[_ProviderMethod], _ProviderMethod]:
    """
    Method decorator for class provider methods in a module class. The provider method can take
    parameters representing dependencies, just like the "@inject()" decorator, and named
    dependencies can be specified in the call to "@class_provider(...)". For details on how this
    works, see the "inject" function's documentation, or look at the README file.

    This decorator does not change the behavior of the method, but it marks it as being a class
    provider (and also stores this in its parent class).

    Note that you must call this decorator like a function (i.e. like "@class_provider()" or
    "@class_provider( ... )", NOT just "@class_provider").
    """
    def handle(provider_method: _ProviderMethod) -> _ProviderMethod:
        return_type: Any = _get_provider_return_type(provider_method, "Class provider")
        if not hasattr(return_type, "__origin__") or return_type.__origin__ is not InjectableClass:
            raise BadProviderError("Class provider \"%s\"'s return type annotation \"%s\" is not "
                                   "of the form InjectableClass(...)" %
                                   (provider_method.__name__, return_type))

        setattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR,
                _ProviderDecoratorProperties(named_dependencies,
                                             return_type.__args__[0],
                                             provided_dependency_name,
                                             True))
        return provider_method
    return handle