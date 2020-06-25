import sys

class Foo:
    def __call__(self):
        print(self, 'hello')


if __name__ == "__main__":
    # print(__name__)
    # foo = Foo()
    # foo()
    print(sys.modules['__main__'])
    print(sys.modules['__main__'].__file__)
    print(getattr(sys.modules['__main__'], '__file__', None))