"""
PyProvide - Barebones dependency injection framework for Python, based on type hints.
For usage, see README.md.

Copyright (c) 2017 Jake Hartz <jake@hartz.io>.
Licensed under the MIT License. For details, see the LICENSE file.
"""

import inspect
import threading
from typing import \
    Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Set, Tuple, Type, TypeVar, Union, \
    cast, get_type_hints

InjectableClassType = TypeVar("InjectableClassType")

# Used as the return type for class providers, like: .... -> InjectableClass[ReturnedClass]
InjectableClass = Callable[..., InjectableClassType]

# Represents an __init__ method of a class
_InitMethod = Callable[..., None]

# Represents the name of a named dependency
_Name = object

# The name of an attribute that is set on methods decorated with one of our decorator functions
_PYPROVIDE_PROPERTIES_ATTR = "_pyprovide_properties"

# Generic type variable used in various functions and methods
T = TypeVar("T")


###################################################################################################
# Exceptions
###################################################################################################


class BadConstructorError(Exception):
    """
    Raised when an invalid __init__ method is decorated with "@inject()".
    """


class BadModuleError(Exception):
    """
    Raised when an invalid module is passed to another module's "install" method or used as an
    argument to Injector's __init__ method.
    """


class BadProviderError(Exception):
    """
    Raised when an invalid provider method is decorated with "@provider()" or "@class_provider()"
    in a module.
    """


class DependencyError(Exception):
    """
    Raised when the injector has an issue providing a dependency.
    """
    def __init__(self, reason: str, dependency_chain: List[type], name: _Name = None) -> None:
        self.reason = reason
        self.dependency_chain = dependency_chain
        self.name = name

    def __str__(self) -> str:
        err = self.reason
        if self.name is not None:
            err += " (\"%s\")" % self.name
        err += ":\n    Dependency: "
        err += "\n    Required by: ".join(str(d) for d in self.dependency_chain)
        return err


###################################################################################################
# "Properties" named tuples (attached to methods decorated with one of our decorator functions)
###################################################################################################


# Properties attached to a method decorated with "@inject(...)"
_InjectDecoratorProperties = NamedTuple("_InjectDecoratorProperties", [
    ("named_dependencies", Dict[str, _Name])
])


# Properties attached to a method decorated with "@provider(...)" or "@class_provider(...)"
_ProviderDecoratorProperties = NamedTuple("_ProviderDecoratorProperties", [
    ("named_dependencies", Dict[str, _Name]),
    ("provided_dependency_type", type),
    ("provided_dependency_name", Optional[_Name]),
    ("is_class_provider", bool)
])


###################################################################################################
# Classes/functions related to providers
###################################################################################################


class _ProviderKey:
    """
    A key for a provider for a dependency, including the provided type and name (if it's for a
    named dependency). This is used to ensure uniqueness of providers in a module or injector's
    registry.
    """
    def __init__(self, provided_dependency_type: type, provided_dependency_name: Optional[_Name],
                 provider_method_name: str = None, containing_module: "Module" = None) -> None:
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

_ProviderMethod = Callable[..., object]


def _is_decorated_class(dependency: type) -> bool:
    # To make the type checker happy (it doesn't like when we access "__init__" directly)
    dependency_unsafe = dependency  # type: Any
    if not hasattr(dependency_unsafe.__init__, _PYPROVIDE_PROPERTIES_ATTR):
        return False
    properties = getattr(dependency_unsafe.__init__, _PYPROVIDE_PROPERTIES_ATTR)
    return isinstance(properties, _InjectDecoratorProperties)


def _get_matching_dict_key(d: Dict[T, Any], k: T) -> Tuple[T, T]:
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


def _get_param_names_and_hints(func: Callable[..., Any],
                               skip_params: int = 0) -> Iterable[Tuple[str, Any]]:
    param_names = list(inspect.signature(func).parameters.keys())[skip_params:]
    type_hints = get_type_hints(func)
    return [(p, type_hints.get(p)) for p in param_names]


###################################################################################################
# Public classes
###################################################################################################


class Module:
    """
    A module defines a specific configuration of dependencies by having provider methods that
    define how to provide dependencies for certain classes. See the README for usage examples.
    """

    def __init__(self) -> None:
        self._providers = {}  # type: Dict[_ProviderKey, _ProviderMethod]
        self._sub_modules = []  # type: List[Module]

        # Register all the providers in this class
        # (requires iterating over all of this class's members, and letting "_register" filter out
        # any that don't have one of our decorators)
        for name, method in inspect.getmembers(self):
            self._register(method, name)

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

        # noinspection PyUnresolvedReferences
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
    """
    An injector holds a registry of providers and manages creating instances of dependencies.
    After an instance of this class is created, its get_instance method can be safely called from
    multiple threads concurrently.
    """

    CURRENT_INJECTOR = object()

    _creating_instance_sentinel = object()

    def __init__(self, *modules: Module) -> None:
        self._lock = threading.RLock()
        self._provider_registry = {}  # type: Dict[_ProviderKey, _ProviderMethod]
        self._instance_registry = {
            _ProviderKey(Injector, Injector.CURRENT_INJECTOR): self
        }  # type: Dict[_ProviderKey, object]
        self._added_modules = set()  # type: Set[Module]

        duplicate_pairs = self._add_modules(modules)
        if len(duplicate_pairs) > 0:
            raise BadModuleError("Found duplicate providers: " +
                                 "; ".join("%s and %s" % (p1, p2) for p1, p2 in duplicate_pairs))

    def _add_modules(self, modules: Iterable["Module"]) -> List[Tuple[_ProviderKey, _ProviderKey]]:
        """
        Add modules, returning a list containing any duplicate providers found while adding them.

        This method is NOT thread-safe.
        """
        duplicate_pairs = []  # type: List[Tuple[_ProviderKey, _ProviderKey]]
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

    def get_instance(self, dependency: Type[T], dependency_name: _Name = None) -> T:
        """
        Get an instance of an injectable class. This method is thread-safe.

        :param dependency: The class that we will return an instance of.
        :param dependency_name: The name of the dependency, if we want a named dependency.
        """
        return self._resolve(dependency, dependency_name)

    def _resolve(self, dependency: Type[T], dependency_name: _Name = None,
                 dependency_chain: List[type] = None) -> T:
        """
        Find or create a provider for a dependency, and call it to get an instance of the
        dependency, returning the result. This method is thread-safe.
        """
        if not dependency_chain:
            dependency_chain = []
        dependency_chain = [cast(type, dependency)] + dependency_chain
        if not isinstance(dependency, type):
            raise DependencyError("Dependency is not a type", dependency_chain, dependency_name)

        provider_key = _ProviderKey(dependency, dependency_name)
        # See if we have a cached instance of this dependency
        if provider_key in self._instance_registry:
            # Make sure it's an actually completely created instance
            if self._instance_registry[provider_key] is not self._creating_instance_sentinel:
                return cast(T, self._instance_registry[provider_key])

        with self._lock:
            # Double-checked locking (https://en.wikipedia.org/wiki/Double-checked_locking)
            # This pattern has lots of naysayers, but should work fine in Python due to the GIL.
            if provider_key in self._instance_registry:
                # Check if it's actually created.
                # If it's not, only one thread can be resolving and creating instances at a time,
                # so it must be a dependency cycle.
                if self._instance_registry[provider_key] is self._creating_instance_sentinel:
                    raise DependencyError("Detected dependency cycle",
                                          dependency_chain, dependency_name)
                # Nope, it's an actual real instance of the dependency we're looking for
                return cast(T, self._instance_registry[provider_key])

            # Try to find a provider for the dependency
            method_or_class = None  # type: Optional[Union[_ProviderMethod, type]]
            if provider_key in self._provider_registry:
                method_or_class = self._provider_registry[provider_key]
            else:
                # We don't have a provider; but if the class is a decorated class, we can pass in
                # the class itself (unless they want a named dependency).
                # This is, essentially, the concept of the "default provider" (spoiler: it's not
                # actually a provider method; that terminology just makes it easier to understand).
                if not dependency_name and _is_decorated_class(dependency):
                    method_or_class = dependency

            if not method_or_class:
                raise DependencyError("Could not find or create provider for dependency",
                                      dependency_chain, dependency_name)

            # Indicate that we're in the process of creating this instance (for cycle detection)
            self._instance_registry[provider_key] = self._creating_instance_sentinel
            # Create the instance
            instance = cast(T, self._call_with_dependencies(method_or_class, dependency_chain))
            # Cache this instance for the future
            self._instance_registry[provider_key] = instance
            return instance

    def _call_with_dependencies(self, method_or_class: Union[_ProviderMethod, type],
                                dependency_chain: List[type]) -> object:
        """
        Get instances of a decorated class's or a provider method's dependencies, and then call the
        method or instantiate the class, returning the result.

        :param method_or_class: Either a decorated class, or a provider method.
        :param dependency_chain: The chain of dependencies that got us to this one (used for error
            messages).
        """
        if not callable(method_or_class):
            raise ValueError("Argument is not a function or a class: %s" % method_or_class)

        def result_handler(result: object) -> object:
            return result

        if inspect.isclass(method_or_class):
            # It's a class (better be a decorated class)
            # To make the type checker happy (it doesn't like when we access "__init__" directly)
            class_unsafe = method_or_class  # type: Any
            params = _get_param_names_and_hints(class_unsafe.__init__, skip_params=1)
            properties = getattr(class_unsafe.__init__, _PYPROVIDE_PROPERTIES_ATTR)
        else:
            # It's a function (better be a provider method)
            provider_method = cast(_ProviderMethod, method_or_class)  # type: _ProviderMethod
            params = _get_param_names_and_hints(provider_method)
            properties = getattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR)

            if properties.is_class_provider:
                # Handle a class provider's return value
                def result_handler(result: object) -> object:
                    if not isinstance(result, type):
                        raise DependencyError("Class provider \"%s\" returned a non-type" %
                                              method_or_class.__name__, dependency_chain)
                    if not _is_decorated_class(result):
                        raise DependencyError("Class provider \"%s\" returned a non-decorated "
                                              "class" % method_or_class.__name__, dependency_chain)
                    return self._call_with_dependencies(result, dependency_chain)

        args = []  # type: List[object]
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


def _check_dependencies(method: Union[_InitMethod, _ProviderMethod],
                        named_dependencies: Dict[str, _Name]) -> Optional[str]:
    """
    Check that all parameters (i.e. dependencies) have a correct type hint, and check that all
    named dependencies have a corresponding parameter that they're attached to.

    Returns the text of an error message, if something was wrong, or None otherwise.
    """
    params = _get_param_names_and_hints(method, skip_params=1)

    # Check that all the arguments have type hints
    naked_params = [name for name, hint in params if not hint]
    if len(naked_params) > 0:
        return "missing type hint annotation for parameters: %s" % naked_params

    # Check that all the type hints are valid
    invalid_params = [name for name, hint in params if not isinstance(hint, type)]
    if len(invalid_params) > 0:
        return "has parameters whose annotations are not types: %s" % invalid_params

    # Check named dependencies
    param_names = {name for name, hint in params}
    unknown_params = [name for name in named_dependencies.keys() if name not in param_names]
    if len(unknown_params) > 0:
        return "has named dependencies that don't correspond to a parameter: %s" % unknown_params

    # All good!
    return None


def inject(**named_dependencies: _Name) -> Callable[[_InitMethod], _InitMethod]:
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
    def handle(init_method: _InitMethod) -> _InitMethod:
        err = _check_dependencies(init_method, named_dependencies)
        if err is not None:
            raise BadConstructorError("Constructor \"%s\" %s" % (init_method, err))

        # noinspection PyCallingNonCallable
        setattr(init_method, _PYPROVIDE_PROPERTIES_ATTR,
                _InjectDecoratorProperties(named_dependencies))
        return init_method
    return handle


def _get_provider_return_type(provider_method: _ProviderMethod, provider_type: str) -> type:
    """
    Validate that a provider method's return type annotation is valid. If it is, then return it;
    otherwise, raise a BadProviderError.
    """
    signature = inspect.signature(provider_method)

    # Validate the return type annotation
    return_type = signature.return_annotation
    if return_type is inspect.Signature.empty:
        raise BadProviderError("%s \"%s\" missing return type annotation" %
                               (provider_type, provider_method.__name__))
    if not isinstance(return_type, type):
        raise BadProviderError("%s \"%s\" return type annotation \"%s\" is not a type" %
                               (provider_type, provider_method.__name__, return_type))

    return return_type


def provider(provided_dependency_name: _Name = None,
             **named_dependencies: _Name) -> Callable[[_ProviderMethod], _ProviderMethod]:
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
        err = _check_dependencies(provider_method, named_dependencies)
        if err is not None:
            raise BadProviderError("Provider \"%s\" %s" % (provider_method.__name__, err))

        provided_dependency_type = _get_provider_return_type(provider_method, "Provider")
        # noinspection PyCallingNonCallable
        setattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR,
                _ProviderDecoratorProperties(named_dependencies,
                                             provided_dependency_type,
                                             provided_dependency_name,
                                             False))
        return provider_method
    return handle


def class_provider(provided_dependency_name: _Name = None,
                   **named_dependencies: _Name) -> Callable[[_ProviderMethod], _ProviderMethod]:
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
        err = _check_dependencies(provider_method, named_dependencies)
        if err is not None:
            raise BadProviderError("Class provider \"%s\" %s" % (provider_method.__name__, err))

        return_type = _get_provider_return_type(provider_method, "Class provider")  # type: Any
        if not hasattr(return_type, "__origin__") or return_type.__origin__ is not InjectableClass:
            raise BadProviderError("Class provider \"%s\"'s return type annotation \"%s\" is not "
                                   "of the form InjectableClass[...]" %
                                   (provider_method.__name__, return_type))

        # noinspection PyCallingNonCallable
        setattr(provider_method, _PYPROVIDE_PROPERTIES_ATTR,
                _ProviderDecoratorProperties(named_dependencies,
                                             return_type.__args__[0],
                                             provided_dependency_name,
                                             True))
        return provider_method
    return handle
