# PyProvide

Barebones dependency injection framework for Python, based on type hints

## Introduction

This documentation assumes that you already know what the dependency injection pattern is. If not,
see [Dependency Injection](https://en.wikipedia.org/wiki/Dependency_injection) on Wikipedia.

This is not meant to be a discussion of how dependency injection works, but rather the specifics of
how it is implemented in PyProvide.

### Key Terms

**Dependency:** A class that is needed by another class or multiple other classes
  - Usually, dependencies are specified as abstract classes that have several possible
    implementations (but this does not have to be the case).

**Named Dependency:** A dependency that is identified by both a name and a type (as opposed to just
a type)

**Decorated class:** A class whose constructor (`__init__` method) is decorated with `@inject`
  - The parameters in the constructor of a decorated class represent its dependencies, and
    instances of these dependencies are passed to the constructor by the injector.
  - Decorated classes do not need providers in order to be injected as dependencies.

**Injectable class:** A class that either has a *provider* or is a *decorated class*
  - Injectable classes can be injected as dependencies to other classes.

**Injector:** A shared object that manages acquiring instances of dependencies
  - To get an instance of a dependency, the injector first looks for a *provider* specified by one
    of the injector's modules; if it cannot find one, but the dependency is a *decorated class*,
    then it uses the *default provider* to get an instance.
  - Injectors cache instances of dependencies, so if multiple classes need the same dependency,
    they will get the same instance. (See "Important Notes" below for more.)

**Provider:** A function that can create an instance of a specific class
  - It usually creates an instance of a specific subclass of the class that it is asked for.
  - Providers are defined as methods on *modules* (see below).
  - The provider is only called once (no matter how many times the dependency is needed), and the
    instance returned from the first call is reused for any future needs of the dependency (i.e.
    every providers is a singleton provider). See "Important Notes" below for more.
  - Just like constructors of decorated classes, provider methods can take in parameters
    representing dependencies.
  - There are 3 types of providers:

    **Instance Provider**: Returns an instance of the class that it provides
      - This is the default type of provider.
      - Instance providers use the `@provider()` decorator.

    **Class Provider**: Rather than returning an instance, returns the class itself
      - The returned class must be a *decorated class* in order for this to work.
      - This is useful if the provider is registered as providing a non-decorated class, but the
        actual class it returns is a subclass of this non-decorated class, and this subclass *is*
        a decorated class.
      - Class providers use the `@class_provider()` decorator.

    **Default Provider**: The provider that is used for all *decorated classes* that do not have
    any other provider
      - This saves you from having to write a provider for simple classes.

**Provider Registry:** A mapping inside the injector of types (i.e. classes) to providers (both
instance providers and class providers)
  - The mapping can contain 2 kinds of entries:

    |                                   |                                 |
    | --------------------------------- | ------------------------------- |
    | **1.** Type --> Provider          | (to handle normal dependencies) |
    | **2.** Name and Type --> Provider | (to handle named dependencies)  |

  - For any given type:
    - Only ONE of the first kind of entry can exist in the registry.
    - One or more of the second kind of entry can exist in the registry, provided each entry has
      a different name.
  - When the injector looks up a type in the registry, it will only match to types that are an
    exact match to the one that it is looking for (it will not match a provider for a superclass or
    subclass of the class it is looking for).

**Module:** A class that contains providers and registers them with an injector's registry
  - Module classes extend the `Module` base class.
  - Modules define providers using the `@provider()` and `@class_provider()` decorators on their
    provider methods.
  - Instances of 0 or more modules are passed to the Injector constructor when creating the
    injector.
  - Modules can "inherit" providers defined in other modules by `install()`'ing them.

## How It Works

1.  Any class with dependencies takes in those dependencies as parameters to its `__init__` method
    (which should be decorated with `@inject()`). This makes the class a *decorated class*:

    ```python
    from pyprovide import inject

    class MyFirstClass:
        # Normal dependencies
        @inject()
        def __init__(self, class_a: ClassA, class_b: ClassB):
            self.class_a = class_a
            self.class_b = class_b
            ...

    class MySecondClass:
        # Named dependencies (In real life, you should probably use constants defined
        #                     in a common place, instead of string literals)
        @inject(class_z_bw="ClassZ in black-and-white", class_z_color="ClassZ in color")
        def __init__(self, class_z_bw: ClassZ, class_z_color: ClassZ):
            self.class_z_bw = class_z_bw
            self.class_z_color = class_z_color
            ...
    ```

    Using `@inject()` does not change the `__init__` method; it still works the same as you would
    expect, even when not creating instances of the class through the dependency injection
    framework (e.g. for unit tests). For more on the way this works, see the "inject" function's
    documentation in *pyprovide.py*.

2.  For each possible configuration of dependencies, define a module class (that extends Module)
    with providers specific to that configuration:

    ```python
    from pyprovide import Module, provider

    class MyModule(Module):
        # This is a simple provider that doesn't need any other instances or dependencies to create
        # an instance of ClassA:
        @provider()
        def provide_class_a(self) -> ClassA:
            return ClassA(arg1, arg2, arg3)

        # This provider requires some dependencies to create an instance of the class it provides.
        # Parameters of provider methods are injected, just like methods that use "@inject()":
        @provider()
        def provide_class_b(self, special_io: SpecialIO) -> ClassB:
            return ClassB(special_io)

        # This even works for named dependencies (just like "@inject()"):
        @provider(class_z_bw="ClassZ in black-and-white")
        def provide_type_c(self, class_z_bw: ClassZ) -> TypeC:
            return TypeC(class_z_bw)
    ```
    
    Note that you don't need a provider for every class. If a class is a *decorated class*, it
    doesn't need a provider as it can use the *default provider* (but it can still have a provider
    defined).

    If a class has a dependency on an abstract class, it is common that the abstract class's
    `__init__` is not a decorated class, but its subclasses are. Then, providers can be used to
    create instances of different subclasses of the abstract class depending on the module that the
    provider is in.

    As a useful shortcut, if the actual instance returned by a provider is a decorated class, then
    you can use a class provider instead of an instance provider (which is what is used above).
    Class providers return class objects themselves, rather than instances of classes.

    ```python
    from pyprovide import Injectable, Module, class_provider

    class MyModule(Module):
        @class_provider()
        def provide_class_a(self) -> Injectable[ClassA]:
            return SubclassOfClassA

        # The provider above is equivalent to:
        @provider()
        def provide_class_a(self, ...dependencies...) -> ClassA:
            return SubclassOfClassA(...dependencies...)
    ```

    Also, remember that the return type annotation of the provider is used when mapping the
    provider in the registry; it is free to return an instance of a subclass.

    To have a provider provide a named dependency, pass the name as an argument to `@provider()`:

    ```python
    from pyprovide import Module, provider

    class MyModule(Module):
        @provider("ClassZ in color")
        def provide(self) -> ClassZ:
            return ClassZ(use_color_plz=True)
    ```

## Important Notes

As specified a few times above, in PyProvide, **all providers are singleton providers**. The value
returned from any provider (including instance providers, class providers, and the default
provider) is cached and reused for any future dependencies on that class.

If you need each class to have a *different instance* of a certain dependency, you can either
inject a factory instead of the class itself, or use a different framework that is more suited to
your needs.
