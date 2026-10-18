"""PyInstaller entry point. Thin on purpose: all real logic is in app.desktop."""
import multiprocessing

from app.desktop import main

if __name__ == "__main__":
    # The render draws segments in worker processes. Frozen, a worker is this
    # same executable started again; freeze_support() is what turns that run
    # into a worker instead of a second copy of the app opening a window.
    multiprocessing.freeze_support()
    main()
