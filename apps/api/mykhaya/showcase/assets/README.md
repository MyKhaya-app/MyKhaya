# Showcase photography (optional)

Family Demo and Ultimate Demo Homes render original MyKhaya illustrations for
recipe, vehicle and profile images. To use photography instead, add files here.
The seeder uses them automatically on the next provision or Reset Showcase Data.
No code change is needed.

Only add images the business holds a licence or model release for, covering
App Store, Google Play, website and marketing use. Don't add images of real
people's children, recognisable private homes or real number plates.

Layout: `<kind>/<slug>.jpg|.jpeg|.png|.webp`.

Every file is decoded, stripped of metadata and re-encoded through the same
pipeline as a user upload before it's stored.

| Kind | Slugs | Notes |
|---|---|---|
| `meals/` | `spaghetti-bolognese`, `creamy-chicken-pasta`, `homemade-burgers`, `thai-green-curry`, `sunday-roast-chicken`, `beef-lasagne`, `chicken-stir-fry`, `cottage-pie`, `pancakes-with-berries`, `fish-and-chips`, `vegetable-pasta-bake`, `chicken-fajitas`, `margherita-pizza`, `tomato-basil-soup`, `greek-salad`, `chocolate-brownies`, `beef-tacos`, `chicken-caesar-salad`, `baked-salmon`, `breakfast-omelette` | 4:3 landscape, at least 1200×900 (1600×1200 recommended). Cards and the recipe header crop to roughly 2:1, so keep the dish in the middle half of the height |
| `vehicles/` | `bmw-i4`, `vw-tiguan`, `mini-cooper` | 16:10 landscape, side or three-quarter view, no legible plate. Driveway shows a centre-cropped square, so keep the whole vehicle inside the middle 60% of the width |
| `avatars/` | `emma`, `james`, `sophie`, `oliver` | Square, cropped to a circle in the app; illustrations recommended |

The slugs are defined in `mykhaya/showcase/parker.py`.

## Planned photography replacements

The built-in illustrations are fine for demos and testing. Replace them with
licensed photography before final App Store and Google Play screenshots, in
this order:

| Priority | Kind | Slugs | Why |
|---|---|---|---|
| 1 | `vehicles/` | `bmw-i4`, `vw-tiguan`, `mini-cooper` | Generic body shapes; the MINI reads as an estate. Driveway is a headline Ultimate screen |
| 2 | `meals/` | `cottage-pie`, `fish-and-chips`, `sunday-roast-chicken`, `thai-green-curry`, `breakfast-omelette`, `baked-salmon` | Weakest illustrations; hard to recognise at card size |
| 3 | `meals/` | `chicken-fajitas`, `beef-tacos` | Look alike next to each other in the Meals grid |
| 4 | `meals/` | every other recipe slug | Consistency: mixing photos and illustrations in one grid looks unfinished |
| — | `avatars/` | `emma`, `james`, `sophie`, `oliver` | Keep the illustrations. Real-looking faces of children add licensing and privacy risk for little benefit |

Recommended sources are commissioned shoots or stock with an extended licence
covering app-store and advertising use. Keep the licence record with the
asset. Use a consistent style across a set (lighting, angle, background), shot
overhead or at 45° for meals.

| Kind | Deliver | Displayed as |
|---|---|---|
| `meals/` | 1600×1200 JPEG, sRGB | Full-width card (about 2:1) and recipe header up to 200px tall |
| `vehicles/` | 1600×1000 JPEG, sRGB | Centre-cropped square thumbnail on the Driveway list and vehicle page |
| `avatars/` | 1024×1024 PNG | Circle, from small attendee chips up to the profile header |

Uploads are resized to at most 2400px on the longest side, so larger files
gain nothing.
