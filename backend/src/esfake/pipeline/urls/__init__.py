"""URL analysis without network requests (ADR-0005, EF-12; CLAUDE.md rule 10).

Nothing in this package opens a socket, resolves a name or follows a link: every signal comes from
the text of the URL and from data files versioned in config/.
"""
