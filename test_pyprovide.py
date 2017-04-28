"""
PyProvide - Barebones dependency injection framework for Python, based on type hints.
For usage, see README.md.

Copyright (c) 2017 Jake Hartz <jake@hartz.io>.
Licensed under the MIT License. For details, see the LICENSE file.
"""

import unittest
from pyprovide import \
    BadConstructorError, BadModuleError, BadProviderError, DependencyError, \
    InjectableClass, InjectableClassType, \
    Injector, Module, \
    class_provider, inject, provider


###################################################################################################
# Injectable classes used in unit tests
###################################################################################################


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


###################################################################################################
# Example modules used in unit tests
###################################################################################################


class ExampleModuleWithInstanceProviders(Module):
    @provider()
    def provide_example_class(self) -> ExampleClass:
        return ExampleSubclass()

    @provider("Named Class A")
    def provide_named_class_a(self) -> ExampleClassA:
        class_a = ExampleClassA()
        class_a.is_the_named_one = True
        return class_a

    @provider("Named Class C", class_a="Named Class A")
    def provide_named_class_c(self, example_class: ExampleClass, class_a: ExampleClassA,
                              class_b: ExampleClassB) -> ExampleClassC:
        assert isinstance(example_class, ExampleClass)
        assert isinstance(class_a, ExampleClassA)
        assert isinstance(class_b, ExampleClassB)
        class_c = ExampleClassC(class_a, class_b)
        class_c.is_the_named_one = True
        return class_c


class ExampleModuleWithClassProviders(Module):
    @class_provider()
    def provide_example_class(self) -> InjectableClass[ExampleClass]:
        return ExampleSubclass

    @class_provider("Named Class A")
    def provide_named_class_a(self) -> InjectableClass[ExampleClassA]:
        class SubclassOfExampleClassA(ExampleClassA):
            pass
        SubclassOfExampleClassA.is_the_named_one = True
        return SubclassOfExampleClassA

    @class_provider("Named Class C", class_a="Named Class A")
    def provide_named_class_c(self, example_class: ExampleClass, class_a: ExampleClassA,
                              class_b: ExampleClassB) -> InjectableClass[ExampleClassC]:
        assert isinstance(example_class, ExampleClass)
        assert isinstance(class_a, ExampleClassA)
        assert hasattr(class_a, "is_the_named_one")
        assert isinstance(class_b, ExampleClassB)
        class SubclassOfExampleClassC(ExampleClassC):
            pass
        SubclassOfExampleClassC.is_the_named_one = True
        return SubclassOfExampleClassC


###################################################################################################
# Actually the unit tests
###################################################################################################


class TestConstructorErrors(unittest.TestCase):
    def test_constructor_without_param_types(self):
        with self.assertRaises(BadConstructorError) as assertion:
            class Test:
                @inject()
                def __init__(self, what, am, i):
                    pass

        self.assertIn("missing type hint annotation for parameters: ['what', 'am', 'i']",
                      str(assertion.exception))

    def test_constructor_with_invalid_param_type(self):
        with self.assertRaises(BadConstructorError) as assertion:
            class Test:
                @inject()
                def __init__(self, dep: 42):
                    pass

        self.assertIn("has parameters whose annotations are not types: ['dep']",
                      str(assertion.exception))

    def test_constructor_with_invalid_named_dependencies(self):
        with self.assertRaises(BadConstructorError) as assertion:
            class Test:
                @inject(class_a="This one's a parameter", class_b="Not actually a parameter")
                def __init__(self, class_a: ExampleClassA):
                    pass

        self.assertIn("has named dependencies that don't correspond to a parameter: ['class_b']",
                      str(assertion.exception))


class TestProviderErrors(unittest.TestCase):
    def test_instance_provider_without_return_type(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @provider()
                def provider_without_return_type(self):
                    pass

        self.assertIn("missing return type annotation", str(assertion.exception))

    def test_class_provider_without_return_type(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @class_provider()
                def provider_without_return_type(self):
                    pass

        self.assertIn("missing return type annotation", str(assertion.exception))

    def test_instance_provider_with_invalid_return_type(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @provider()
                def provider_with_bad_return_type(self) -> 42:
                    pass

        self.assertIn("return type annotation \"42\" is not a type", str(assertion.exception))

    def test_class_provider_with_invalid_return_type(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @class_provider()
                def provider_with_bad_return_type(self) -> 42:
                    pass

        self.assertIn("return type annotation \"42\" is not a type", str(assertion.exception))

        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @class_provider()
                def provider_with_invalid_return_type(self) -> ExampleClass:
                    pass

        self.assertRegex(str(assertion.exception),
                         r'return type annotation .* is not of the form '
                         r'InjectableClass\[\.\.\.\]$')

    def test_instance_provider_without_param_types(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @provider()
                def provider_without_param_types(self, what, am, i) -> ExampleClass:
                    pass

        self.assertIn("missing type hint annotation for parameters: ['what', 'am', 'i']",
                      str(assertion.exception))

    def test_class_provider_without_param_types(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @class_provider()
                def provider_without_param_types(self, what, am, i) -> \
                        InjectableClass[ExampleClass]:
                    pass

        self.assertIn("missing type hint annotation for parameters: ['what', 'am', 'i']",
                      str(assertion.exception))

    def test_instance_provider_with_invalid_param_type(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @provider()
                def provider_with_invalid_param_type(self, dep: 42) -> ExampleClass:
                    pass

        self.assertIn("has parameters whose annotations are not types: ['dep']",
                      str(assertion.exception))

    def test_class_provider_with_invalid_param_type(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @class_provider()
                def provider_with_invalid_param_type(self, dep: 42) -> \
                        InjectableClass[ExampleClass]:
                    pass

        self.assertIn("has parameters whose annotations are not types: ['dep']",
                      str(assertion.exception))

    def test_instance_provider_with_invalid_named_dependencies(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @provider(class_a="This one's a parameter", class_b="Not actually a parameter")
                def provider_with_invalid_named_deps(self, class_a: ExampleClassA) -> ExampleClass:
                    pass

        self.assertIn("has named dependencies that don't correspond to a parameter: ['class_b']",
                      str(assertion.exception))

    def test_class_provider_with_invalid_named_dependencies(self):
        with self.assertRaises(BadProviderError) as assertion:
            class TestModule(Module):
                @class_provider(class_a="This one's real", class_b="Not actually a parameter")
                def provider_with_invalid_named_deps(self, class_a: ExampleClassA) -> \
                        InjectableClass[ExampleClass]:
                    pass

        self.assertIn("has named dependencies that don't correspond to a parameter: ['class_b']",
                      str(assertion.exception))

    def test_inject_decorated_method_in_module(self):
        class TestModule(Module):
            @inject()
            def provider_annotated_with_inject(self):
                pass

        with self.assertRaises(BadProviderError) as assertion:
            TestModule()

        self.assertIn("is decorated with an invalid decorator", str(assertion.exception))


class TestDependencyErrors(unittest.TestCase):
    def test_dependency_cycle(self):
        class Example1:
            pass
        class Example2:
            @inject()
            def __init__(self, example1: Example1): pass
        class Example3:
            @inject()
            def __init__(self, example2: Example2): pass
        class ExampleModule(Module):
            @provider()
            def provide_example_1(self, example3: Example3) -> Example1:
                return Example1()

        injector = Injector(ExampleModule())
        with self.assertRaises(DependencyError) as assertion:
            injector.get_instance(Example1)
        self.assertEqual(assertion.exception.reason, "Detected dependency cycle")

    def test_no_provider_for_dependency(self):
        class Example1:
            def __init__(self):
                pass

        class Example2:
            @inject()
            def __init__(self, example1: Example1):
                pass

        injector = Injector()

        with self.assertRaises(DependencyError) as assertion:
            injector.get_instance(Example1)
        self.assertEqual(assertion.exception.reason,
                         "Could not find or create provider for dependency")

        with self.assertRaises(DependencyError) as assertion:
            injector.get_instance(Example2)
        self.assertEqual(assertion.exception.reason,
                         "Could not find or create provider for dependency")

    def test_class_provider_returned_non_type(self):
        class TestModule(Module):
            @class_provider()
            def provide_example_class(self) -> InjectableClass[ExampleClass]:
                return 42

        injector = Injector(TestModule())
        with self.assertRaises(DependencyError) as assertion:
            injector.get_instance(ExampleClass)
        self.assertRegex(assertion.exception.reason,
                         r'^Class provider ".*" returned a non-type$')

    def test_class_provider_returned_non_decorated_class(self):
        class TestModule(Module):
            @class_provider()
            def provide_example_class(self) -> InjectableClass[ExampleClass]:
                return ExampleClass

        injector = Injector(TestModule())
        with self.assertRaises(DependencyError) as assertion:
            injector.get_instance(ExampleClass)
        self.assertRegex(assertion.exception.reason,
                         r'^Class provider ".*" returned a non-decorated class$')


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
        # Ensure that the "singleton provider" promise is met
        self.assertIs(class_c.class_a, class_c.class_b.class_a)

    def test_injecting_current_injector(self):
        class Test:
            @inject(injector=Injector.CURRENT_INJECTOR)
            def __init__(self, injector: Injector):
                self.injector = injector

        injector = Injector()
        test = injector.get_instance(Test)
        self.assertIs(test.injector, injector)


class TestInjectionWithProviders(unittest.TestCase):
    def test_providing_subclass(self):
        for m in [ExampleModuleWithInstanceProviders, ExampleModuleWithClassProviders]:
            with self.subTest(module=m):
                injector = Injector(m())

                example_class = injector.get_instance(ExampleClass)
                self.assertIsInstance(example_class, ExampleSubclass)

                example_class_again = injector.get_instance(ExampleClass)
                self.assertIs(example_class_again, example_class)

    def test_providing_named_dependency(self):
        for m in [ExampleModuleWithInstanceProviders, ExampleModuleWithClassProviders]:
            with self.subTest(module=m):
                injector = Injector(m())

                named_class_a = injector.get_instance(ExampleClassA, "Named Class A")
                self.assertIsInstance(named_class_a, ExampleClassA)
                self.assertTrue(hasattr(named_class_a, "is_the_named_one"))

                named_class_a_again = injector.get_instance(ExampleClassA, "Named Class A")
                self.assertIs(named_class_a_again, named_class_a)

    def test_providing_named_dependency_with_dependencies_from_instance_provider(self):
        injector = Injector(ExampleModuleWithInstanceProviders())

        named_class_c = injector.get_instance(ExampleClassC, "Named Class C")
        self.assertIsInstance(named_class_c, ExampleClassC)
        self.assertTrue(hasattr(named_class_c, "is_the_named_one"))

        self.assertIsInstance(named_class_c.class_a, ExampleClassA)
        self.assertIsInstance(named_class_c.class_b, ExampleClassB)
        self.assertIsInstance(named_class_c.class_b.class_a, ExampleClassA)

        # ExampleClassC's class_a should be the named version;
        # ExampleClassB's class_a should not
        self.assertTrue(hasattr(named_class_c.class_a, "is_the_named_one"))
        self.assertFalse(hasattr(named_class_c.class_b.class_a, "is_the_named_one"))
        self.assertIsNot(named_class_c.class_a, named_class_c.class_b.class_a)

    def test_providing_named_dependencies_with_dependencies_from_class_provider(self):
        injector = Injector(ExampleModuleWithClassProviders())

        named_class_c = injector.get_instance(ExampleClassC, "Named Class C")
        self.assertIsInstance(named_class_c, ExampleClassC)
        # Make sure it's the named subclass, not the class itself
        self.assertTrue(type(named_class_c) is not ExampleClassC)
        self.assertTrue(hasattr(named_class_c, "is_the_named_one"))

        self.assertIsInstance(named_class_c.class_a, ExampleClassA)
        self.assertIsInstance(named_class_c.class_b, ExampleClassB)
        self.assertIsInstance(named_class_c.class_b.class_a, ExampleClassA)

        # The class_a attribute of ExampleClassC and ExampleClassB should be the same
        self.assertIs(named_class_c.class_a, named_class_c.class_b.class_a)

    def test_providing_different_injectable_subclass(self):
        class Dep1:
            @inject()
            def __init__(self): pass
        class Dep2:
            @inject()
            def __init__(self): pass
        class Dep3:
            @inject()
            def __init__(self): pass

        class Class1:
            @inject()
            def __init__(self, dep1: Dep1, dep2: Dep2):
                self.class1_dep1 = dep1
                self.class1_dep2 = dep2

        class Class2(Class1):
            @inject()
            def __init__(self, dep2: Dep2, dep3: Dep3):
                super().__init__("DEP 1", "DEP 2")
                self.class2_dep2 = dep2
                self.class2_dep3 = dep3

        injector_without_module = Injector()
        instance = injector_without_module.get_instance(Class1)
        self.assertIsInstance(instance, Class1)
        self.assertIsInstance(instance.class1_dep1, Dep1)
        self.assertIsInstance(instance.class1_dep2, Dep2)

        class TestModule(Module):
            @class_provider()
            def provide_class_1(self) -> InjectableClass[Class1]:
                return Class2

            @class_provider("class 1 named directly")
            def provide_class_1_named(self) -> InjectableClass[Class1]:
                return Class1

        injector_with_module = Injector(TestModule())

        instance = injector_with_module.get_instance(Class1)
        self.assertIsInstance(instance, Class2)
        self.assertEqual(instance.class1_dep1, "DEP 1")
        self.assertEqual(instance.class1_dep2, "DEP 2")
        self.assertIsInstance(instance.class2_dep2, Dep2)
        self.assertIsInstance(instance.class2_dep3, Dep3)

        instance = injector_with_module.get_instance(Class1, "class 1 named directly")
        self.assertIsInstance(instance, Class1)
        self.assertNotIsInstance(instance, Class2)
        self.assertIsInstance(instance.class1_dep1, Dep1)
        self.assertIsInstance(instance.class1_dep2, Dep2)

    def test_providing_superclass(self):
        class SuperClass:
            def __init__(self, non_dep_arg):
                self.non_dep_arg = non_dep_arg
        class SubClass(SuperClass):
            @inject()
            def __init__(self):
                super().__init__("FROM SubClass")
                self.from_provider = False

        class TestModule(Module):
            @provider()
            def provide_super_class(self) -> SuperClass:
                sub_class = SubClass()
                sub_class.from_provider = True
                return sub_class

        injector = Injector(TestModule())
        instance = injector.get_instance(SuperClass)
        self.assertIsInstance(instance, SubClass)
        self.assertTrue(instance.from_provider)

        # Ensure that it won't use the SuperClass provider if we get SubClass directly
        instance = injector.get_instance(SubClass)
        self.assertIsInstance(instance, SubClass)
        self.assertFalse(instance.from_provider)


if __name__ == "__main__":
    unittest.main()
