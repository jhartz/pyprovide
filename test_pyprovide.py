import unittest
from pyprovide import \
    BadModuleError, BadProviderError, DependencyError, \
    InjectableClass, InjectableClassType, \
    Injector, Module, \
    class_provider, inject, provider


class ExampleClass:
    pass


class ExampleSubclass(ExampleClass):
    @inject()
    def __init__(self):
        pass


class ExampleClass2:
    @inject()
    def __init__(self, example_class: ExampleClass):
        self.example_class = example_class


class ExampleClassA:
    @inject()
    def __init__(self):
        pass


class ExampleClassB:
    @inject()
    def __init__(self, class_a: ExampleClassA):
        self.class_a = class_a


class ExampleClassC:
    @inject()
    def __init__(self, class_a: ExampleClassA, class_b: ExampleClassB):
        self.class_a = class_a
        self.class_b = class_b


class ExampleClassD:
    @inject(class_a="Named Class A", class_c="Named Class C")
    def __init__(self, class_a: ExampleClassA, class_b: ExampleClassB, class_c: ExampleClassC):
        self.class_a = class_a
        self.class_b = class_b
        self.class_c = class_c


class ExampleModuleWithInstanceProviders(Module):
    @provider()
    def provide_example_class(self) -> ExampleClass:
        example_class: ExampleClass = ExampleSubclass()
        return example_class

    @provider("Named Class A")
    def provide_named_class_a(self) -> ExampleClassA:
        class_a: ExampleClassA = ExampleClassA()
        class_a.is_the_named_one = True
        return class_a

    @provider("Example Class C", class_a="Named Class A")
    def provide_named_class_c(self, example_class: ExampleClass, class_a: ExampleClassA,
                              class_b: ExampleClassB) -> ExampleClassC:
        class_c: ExampleClassC = ExampleClassC(example_class, class_a, class_b)
        return class_c


class ExampleModuleWithClassProviders(Module):
    @class_provider()
    def provide_example_class(self) -> InjectableClass[ExampleClass]:
        return ExampleSubclass

    @class_provider("Named Class A")
    def provide_named_class_a(self) -> InjectableClass[ExampleClassA]:
        class SubclassOfExampleClassA(ExampleClassA):
            @inject()
            def __init__(self):
                super().__init__()
        SubclassOfExampleClassA.is_the_named_class = True
        return SubclassOfExampleClassA

    @class_provider("Example Class C", class_a="Named Class A")
    def provide_named_class_c(self, example_class: ExampleClass, class_a: ExampleClassA,
                              class_b: ExampleClassB) -> InjectableClass[ExampleClassC]:
        assert isinstance(example_class, ExampleClass)
        assert isinstance(class_a, ExampleClassA)
        assert isinstance(class_b, ExampleClassB)
        return ExampleClassC


class TestInvalidProviders(unittest.TestCase):
    def test_provider_without_return_type(self):
        with self.assertRaises(BadProviderError):
            class ExampleModuleWithInvalidProvider1(Module):
                @provider()
                def provider_without_return_type(self):
                    pass

    def test_provider_without_param_types(self):
        with self.assertRaises(BadProviderError):
            class ExampleModuleWithInvalidProvider2(Module):
                @provider()
                def provider_without_param_types(self, what, am, i) -> ExampleClass:
                    pass


class TestInjectionWithDefaultProvider(unittest.TestCase):
    def test_with_class_with_no_dependences(self):
        injector = Injector()
        class_a = injector.get_instance(ExampleClassA)
        self.assertIsInstance(class_a, ExampleClassA)

    def test_with_class_with_one_dependency(self):
        injector = Injector()
        class_b = injector.get_instance(ExampleClassB)
        self.assertIsInstance(class_b, ExampleClassB)
        self.assertIsInstance(class_b.class_a, ExampleClassA)

    def test_with_recursive_dependencies(self):
        injector = Injector()
        class_c = injector.get_instance(ExampleClassC)
        self.assertIsInstance(class_c, ExampleClassC)
        self.assertIsInstance(class_c.class_a, ExampleClassA)
        self.assertIsInstance(class_c.class_b, ExampleClassB)
        self.assertIsInstance(class_c.class_b.class_a, ExampleClassA)
        # TODO: Singleton-ness not yet enforced
        # TODO: Uncomment this assertion when it is
        #self.assertIs(class_c.class_a, class_c.class_b.class_a)


if __name__ == "__main__":
    unittest.main()