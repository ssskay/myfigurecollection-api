"""Parsers for ``/club/{id}`` and ``/club/{id}/members/``.

Clubs are the one thing tenji never covered, and the reason this package
exists at all — MFC's own API club (#349) is where the dead API is documented.
"""

from __future__ import annotations

from bs4 import Tag

from ..models import Club, ClubComment, ClubMember, ClubMembers, ClubThread
from .base import Parser


class ClubParser(Parser):
    def __init__(self, html: str, *, club_id: int | None = None, url=None) -> None:
        super().__init__(html, url=url)
        self.club_id = club_id

    def parse(self) -> Club:
        club_id = self.club_id or self.number(self.text("a.current"))
        if club_id is None:
            self.require(None, "the club id")

        name = self.text("h1.title")
        if name is None:
            self.require(None, "the club headline")

        stats = self.soup.select_one("div.object-stats")
        updated = stats.select_one("span[title]") if stats else None
        member_count = comment_count = None
        if stats is not None:
            members_link = stats.select_one("a[href*='/members/']")
            comments_link = stats.select_one("a[href*='/comments/']")
            member_count = self.number(members_link.get_text(" ", strip=True)) if members_link else None
            comment_count = self.number(comments_link.get_text(" ", strip=True)) if comments_link else None

        return Club(
            id=club_id,
            name=name,
            url=f"https://myfigurecollection.net/club/{club_id}",
            subtitle=self.text("div.subtitle") or None,
            icon=self.attr("a.content-icon img, div.content-icon img", "src"),
            category=self.text("div.categories a"),
            description=self._description(),
            member_count=member_count,
            comment_count=comment_count,
            updated=self.timestamp(updated),
            updated_relative=updated.get_text(" ", strip=True) if updated else None,
            threads=self._threads(),
            comments=self._comments(),
            staff=self._members_in_section("Staff"),
            members=self._members_in_section("Members"),
        )

    def _description(self) -> str | None:
        """The club blurb is the first ``div.bbcode`` that is not inside a comment."""
        for block in self.soup.select("div.bbcode"):
            if block.find_parent(class_="comment") is None:
                text = block.get_text(" ", strip=True)
                if text:
                    return text
        return None

    def _threads(self) -> list[ClubThread]:
        threads: list[ClubThread] = []
        for dgst in self.soup.select("div.dgst.dgst-thread"):
            anchor = dgst.select_one("a.thread-name")
            if anchor is None:
                continue
            thread_id = self.trailing_id(anchor.get("href"))
            if thread_id is None:
                continue

            metas = dgst.select("div.dgst-meta")
            last_poster = self.text("a.user-anchor", dgst)
            replies = next(
                (
                    self.number(span.get_text(" ", strip=True))
                    for span in dgst.select("span.meta")
                    if "repl" in span.get_text(" ", strip=True)
                ),
                None,
            )

            times = dgst.select("span[title]")
            last_post = self.timestamp(times[0]) if times else None
            started = self.timestamp(times[-1]) if len(times) > 1 else None

            started_by = None
            if len(metas) > 1:
                links = metas[-1].select("a[href*='/profile/']")
                started_by = links[0].get_text(" ", strip=True) if links else None

            threads.append(
                ClubThread(
                    id=thread_id,
                    title=anchor.get("title") or anchor.get_text(" ", strip=True),
                    url=self.absolute(anchor.get("href")),
                    status=self.text("span.meta.category", dgst),
                    started_by=started_by,
                    started=started,
                    last_poster=last_poster,
                    last_post=last_post,
                    replies=replies,
                )
            )
        return threads

    def _comments(self) -> list[ClubComment]:
        comments: list[ClubComment] = []
        for node in self.soup.select("div.comment"):
            username = self.text("div.user-expression-username a.user-anchor", node)
            body = self.text("div.bbcode", node)
            if username is None or body is None:
                continue
            posted = node.select_one("div.user-expression-meta span[title]")
            comments.append(
                ClubComment(
                    username=username,
                    avatar=self.attr("a.user-expression-avatar img", "src", node),
                    body=body,
                    posted=self.timestamp(posted),
                    posted_relative=posted.get_text(" ", strip=True) if posted else None,
                )
            )
        return comments

    def _members_in_section(self, heading: str) -> list[ClubMember]:
        for section in self.soup.select("section"):
            title = section.select_one("h2")
            if title is None or not title.get_text(" ", strip=True).startswith(heading):
                continue
            return [m for m in (self._member(s) for s in section.select("div.user-stamp")) if m]
        return []

    def _member(self, stamp: Tag) -> ClubMember | None:
        anchor = stamp.select_one("div.stamp-anchor a[href]") or stamp.select_one("a[href]")
        if anchor is None:
            return None
        result = stamp.find_parent(class_="result")
        role = None
        if result is not None:
            role_node = result.select_one("div.result-actions span[class*=club-user-team], div.result-actions span")
            role = role_node.get_text(" ", strip=True) if role_node else None
        return ClubMember(
            username=anchor.get_text(" ", strip=True),
            url=self.absolute(anchor.get("href")),
            avatar=self.attr("img.stamp-icon", "src", stamp),
            role=role or None,
        )


class ClubMembersParser(ClubParser):
    """``/club/{id}/members/`` — the full, paginated member roster."""

    def parse(self) -> ClubMembers:  # type: ignore[override]
        club_id = self.club_id or self.number(self.text("a.current"))
        members = [
            m for m in (self._member(s) for s in self.soup.select("div.user-stamp")) if m
        ]
        return ClubMembers(
            club_id=club_id or 0, members=members, pagination=self.pagination()
        )
