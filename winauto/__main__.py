import sys

if "--selftest" in sys.argv:
    from winauto.selftest import main
elif "--cli" in sys.argv:
    from winauto.cli import main
else:
    from winauto.app import main

sys.exit(main())
