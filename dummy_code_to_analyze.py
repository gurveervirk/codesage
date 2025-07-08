
import os
from collections import Counter

GLOBAL_VAR: int = 100
MODULE_LEVEL_STR = "hello"

class MyClass:
    class_var: float = 3.14

    def __init__(self, name: str):
        self.name = name
        self.instance_id = self.generate_id()
        self.counter_obj = Counter() # External call example

    def greet(self, greeting: str = "Hello") -> str:
        local_var = f"{greeting}, {self.name}!"
        result_len = len(local_var) # Built-in, thus external
        return local_var

    def generate_id(self) -> int:
        return os.urandom(4).hex() # External call to os module

def module_func(param_a: int, param_b=None):
    temp_var = param_a * GLOBAL_VAR
    another_var = MyClass("test") # Internal class instantiation
    another_var.greet("Hi") # Internal method call
    print(MODULE_LEVEL_STR) # Built-in print, external
    print("Function done.")

def external_dependency_call_example():
    path = os.path.join("a", "b") # External call
    return path

# Module-level calls
module_func(GLOBAL_VAR)
my_instance = MyClass("World") # Internal class instantiation
my_instance.greet() # Internal method call
my_instance.generate_id() # Internal method call
external_dependency_call_example()
list_var = [1, 2, 3]
dict_var = {"key": "value"}
bool_var = True
