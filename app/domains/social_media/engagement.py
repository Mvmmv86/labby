import random
from dataclasses import dataclass

from app.integrations.x_api import XPost


@dataclass(frozen=True)
class SortedNewsCandidate:
    post: XPost
    engagement_score: float
    ranking_source: str | None
    ranking_reason: str


@dataclass(frozen=True)
class EngagementSortResult:
    ranked: list[SortedNewsCandidate]
    discarded: list[SortedNewsCandidate]


class NewsEngagementSorter:
    def engagement_score(self, post: XPost) -> float:
        return round(
            post.like_count
            + post.retweet_count * 2
            + post.reply_count * 3
            + post.quote_count * 2
            + post.impression_count * 0.001,
            2,
        )

    def sort(
        self,
        posts: list[XPost],
        *,
        min_engagement_score: int = 0,
        limit: int = 5,
        exploration_slots: int = 1,
        random_seed: int | None = None,
    ) -> EngagementSortResult:
        scored = [
            SortedNewsCandidate(
                post=post,
                engagement_score=self.engagement_score(post),
                ranking_source=None,
                ranking_reason="capturado",
            )
            for post in posts
        ]
        ordered = sorted(scored, key=self._sort_key)
        eligible = [
            item for item in ordered if item.engagement_score >= min_engagement_score
        ]
        below_threshold = [
            self._with_reason(
                item,
                None,
                "descartado: engagement_score "
                f"{item.engagement_score:.2f} abaixo do threshold {min_engagement_score}",
            )
            for item in ordered
            if item.engagement_score < min_engagement_score
        ]

        top_slots = max(limit - exploration_slots, 0)
        ranked = [
            self._with_reason(
                item,
                "top_engagement",
                f"top engagement: score {item.engagement_score:.2f}",
            )
            for item in eligible[:top_slots]
        ]

        exploration_pool = eligible[top_slots:]
        if exploration_pool and len(ranked) < limit and exploration_slots > 0:
            exploration = random.Random(random_seed).choice(exploration_pool)
            ranked.append(
                self._with_reason(
                    exploration,
                    "exploration",
                    f"slot exploracao: score {exploration.engagement_score:.2f}",
                )
            )

        ranked_ids = {item.post.id for item in ranked}
        discarded = [
            self._with_reason(
                item,
                None,
                f"descartado: fora do top {limit} por engagement_score "
                f"{item.engagement_score:.2f}",
            )
            for item in eligible
            if item.post.id not in ranked_ids
        ]
        discarded.extend(below_threshold)
        return EngagementSortResult(ranked=ranked, discarded=discarded)

    def _sort_key(self, item: SortedNewsCandidate) -> tuple[float, float, str]:
        timestamp = item.post.created_at.timestamp() if item.post.created_at else float("-inf")
        return (-item.engagement_score, -timestamp, item.post.id)

    def _with_reason(
        self,
        item: SortedNewsCandidate,
        ranking_source: str | None,
        ranking_reason: str,
    ) -> SortedNewsCandidate:
        return SortedNewsCandidate(
            post=item.post,
            engagement_score=item.engagement_score,
            ranking_source=ranking_source,
            ranking_reason=ranking_reason,
        )
