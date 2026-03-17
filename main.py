import sys

from tele_backup.cli import main


if __name__ == '__main__':
    raise SystemExit(main(['daemon', *sys.argv[1:]]))
