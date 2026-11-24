"""Lançador compatível da interface gráfica Tkinter."""

from urna_app.gui import *  # noqa: F401,F403
from urna_app.database import DatabaseError

if __name__ == "__main__":
    try:
        App().mainloop()
    except DatabaseError as erro:
        print(f"Não foi possível iniciar o banco local: {erro}")
