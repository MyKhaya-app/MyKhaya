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
| `meals/` | `spaghetti-bolognese`, `creamy-chicken-pasta`, `homemade-burgers`, `thai-green-curry`, `sunday-roast-chicken`, `beef-lasagne`, `chicken-stir-fry`, `cottage-pie`, `pancakes-with-berries`, `fish-and-chips`, `vegetable-pasta-bake`, `chicken-fajitas`, `margherita-pizza`, `tomato-basil-soup`, `greek-salad`, `chocolate-brownies`, `beef-tacos`, `chicken-caesar-salad`, `baked-salmon`, `breakfast-omelette` | 4:3 landscape, at least 1200×900 |
| `vehicles/` | `bmw-i4`, `vw-tiguan`, `mini-cooper` | 16:10 landscape, side or three-quarter view, no legible plate. Driveway shows a centre-cropped square, so keep the whole vehicle inside the middle 60% of the width |
| `avatars/` | `emma`, `james`, `sophie`, `oliver` | Square, cropped to a circle in the app; illustrations recommended |

The slugs are defined in `mykhaya/showcase/parker.py`.
