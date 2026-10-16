import sys

# `python -m pelicula <comando>` usa o modo terminal; sem comando (ou com arquivos), abre a janela.
if len(sys.argv) > 1 and sys.argv[1] in __import__("pelicula.cli", fromlist=["COMMANDS"]).COMMANDS:
    from .cli import main as cli_main

    sys.exit(cli_main(sys.argv[1:]))

from .app import main

sys.exit(main())
