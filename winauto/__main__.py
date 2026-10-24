import sys

if "--cli" in sys.argv:
    from winauto.cli import main
else:
    from winauto.app import main

sys.exit(main())
