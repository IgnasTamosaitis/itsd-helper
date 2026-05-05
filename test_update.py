"""
Run this script to test the self-update flow without a GitHub release.
It stages the current directory's files and fires the PS1 exactly as a
real update would. The app will close and reopen if everything works.

Usage:
    pythonw test_update.py
"""
import sys
import tkinter as tk
import tkinter.messagebox as mb

import updater

root = tk.Tk()
root.withdraw()

if not mb.askyesno(
    "Test update",
    "This will close the app and reopen it via the update PS1.\n\n"
    "Check update.log in the app folder afterwards.\n\nContinue?",
):
    sys.exit()

updater.simulate_local_update(new_version="test")
root.quit()
