class ActionNotApplicable(Exception):
    """A confirmed suggestion can no longer be applied (e.g. its target was deleted)."""
