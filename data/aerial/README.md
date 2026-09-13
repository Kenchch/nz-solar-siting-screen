# Aerial review evidence

One image per site in `outputs/osm/aerial_review_queue.csv`, named by `site_id`.
Each is a 3 × 3 mosaic of LINZ Basemaps aerial tiles at WebMercatorQuad zoom 14,
centred on the polygon centroid, with the centroid ringed in red. At this
latitude a z14 tile is about 1,765 m wide, so the mosaic covers roughly
**5.3 km across at 6.9 m per pixel**. These are the exact images the verdicts in
[`../aerial_review_log.csv`](../aerial_review_log.csv) were written from, so a
reader can check a claim without re-fetching anything.

`observed_detail` in that log names something visible in the image — an aircraft
on a grass airstrip, a sand island in the lagoon, the distance to a surf line —
so a verdict can be falsified against the picture rather than taken on trust.

**Who reviewed these.** Three passes, each recorded separately. An AI agent
(Claude Opus 5) made a first pass and a second pass with the same tooling - same
agent, same images, so it is a careful re-read and not an independent opinion.
The repository author then reviewed all twenty and confirmed them on
13 September 2026. The genuinely independent checks are that confirmation and
the measured geometry: every distance in the log comes from the polygons, not
from an estimate off a picture. The log carries `reviewer`, `second_pass_on`,
`second_pass_result` and `author_confirmed_on` so the three are distinguishable
rather than collapsed into one claim. To check any of them yourself, open the
image here or the `basemaps_url` in the queue file.

The verdicts are a human-confirmed screening judgement from aerial imagery. They
are not a site visit and not a signed technical assessment.

The second pass confirmed all twenty verdicts and corrected two things. The
first pass had taken the per-tile width for the mosaic width, so the distances
it read off the images were roughly three times too small; those are now
measured from the geometry and published as `centroid_to_coastline_m` and
`centroid_to_water_m`. And one site described as an "enclosed valley floor"
turned out, once slope was measured, to be mostly steep valley sides.

Imagery © LINZ and Environment Canterbury, CC BY 4.0 (Canterbury and Selwyn
rural aerial photography, 0.2–0.3 m, 2024–2025). Redistributed here under that
licence for the purpose of evidencing the review.
