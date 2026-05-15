import sys

def get_argv(key):
    try:
        index = sys.argv.index(key)

        if len(sys.argv) - 1 >= index + 1:
            return sys.argv[index + 1]
        else:
            return None
    except ValueError:
        return None