"""Entry point of Pravachanam Shorts."""
import multiprocessing

from pshorts.server import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
