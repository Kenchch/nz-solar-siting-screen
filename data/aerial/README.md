# Aerial review evidence

One image per site in `outputs/osm/aerial_review_queue.csv`, named by `site_id`.
Each is a 3 × 3 mosaic of LINZ Basemaps aerial tiles at WebMercatorQuad zoom 14
(about 1.7 km across), centred on the polygon centroid, with the centroid ringed
in red. These are the exact images the verdicts in
[`../aerial_review_log.csv`](../aerial_review_log.csv) were written from, so a
reader can check a claim without re-fetching anything.

`observed_detail` in that log names something visible in the image — an aircraft
on a grass airstrip, a sand island in the lagoon, the distance to a surf line —
so a verdict can be falsified against the picture rather than taken on trust.

**Who reviewed these.** The verdicts were made by an AI agent (Claude Opus 5)
working in the repository author's session, from these images. No person has
independently confirmed them. That is recorded in the `reviewer` column of the
log rather than implied, because the whole point of the exercise is that a
screening claim should be checkable. To re-do any of them yourself, open the
`basemaps_url` in the queue file.

Imagery © LINZ and Environment Canterbury, CC BY 4.0 (Canterbury and Selwyn
rural aerial photography, 0.2–0.3 m, 2024–2025). Redistributed here under that
licence for the purpose of evidencing the review.
