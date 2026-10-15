from django.utils import timezone

from core.entity import Bookmark


class BookmarkController:
    """
    «Control» BookmarkController — session-only bookmarks (decision 10).

    - UC-05 Bookmark Resale Flat (FR 2.2.4.1)
    - UC-14 View Bookmarked Flats (FR 2.2.4.2)

    Bookmarks are stored in the Django session as a list of Bookmark dicts; nothing
    is written to a user table (NFR 4). They last as long as the browser session.
    """

    SESSION_KEY = "bookmarks"

    def toggle_bookmark(self, session, flat_id: int) -> bool:
        """UC-05 / UC-05.AC.1: add the bookmark, or remove it if present. Returns the new state."""
        flat_id = int(flat_id)
        bookmarks = self._load(session)
        if any(b.flat_id == flat_id for b in bookmarks):
            self._store(session, [b for b in bookmarks if b.flat_id != flat_id])
            return False
        bookmarks.append(Bookmark(session_id=self._session_id(session), flat_id=flat_id, timestamp=timezone.now()))
        self._store(session, bookmarks)
        return True

    def is_bookmarked(self, session, flat_id: int) -> bool:
        return int(flat_id) in self.bookmarked_ids(session)

    def get_bookmarks(self, session) -> list:
        """
        UC-14: the session's Bookmarks, newest first. Ties (Windows clocks can give two
        toggles the same timestamp) fall back to the order they were added.
        """
        ordered = enumerate(self._load(session))
        return [b for _, b in sorted(ordered, key=lambda item: (item[1].timestamp, item[0]), reverse=True)]

    def bookmarked_ids(self, session) -> set:
        return {b.flat_id for b in self._load(session)}

    def forget(self, session, flat_ids) -> None:
        """Drop bookmarks for flats that no longer exist (e.g. after a re-import)."""
        flat_ids = {int(i) for i in flat_ids}
        if flat_ids:
            self._store(session, [b for b in self._load(session) if b.flat_id not in flat_ids])

    # --- Session storage ------------------------------------------------------------

    def _load(self, session) -> list:
        return [Bookmark.from_session(item) for item in session.get(self.SESSION_KEY, [])]

    def _store(self, session, bookmarks) -> None:
        session[self.SESSION_KEY] = [b.to_session() for b in bookmarks]
        session.modified = True

    @staticmethod
    def _session_id(session) -> str:
        if not session.session_key:
            session.save()  # a new visitor's session gets its key on first save
        return session.session_key
