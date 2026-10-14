# Historical bird artwork

This is a reviewed starter library for the local BirdNET
species list: **23 species, 25 transparent variants**. All birds are excerpts
from historical illustrations, not generated artwork or photographs. House
Finch has male/female variants; European Starling has summer/winter plumages.
Variant choice is artistic, not an inference of an individual bird's sex or
plumage from an audio detection.

`manifest.json` is the renderer-facing catalogue. Each entry has a stable ID,
scientific/common name, prepared PNG path, source scan path, artist, date,
source/rights links, and SHA-256 hashes for both files. `ingestion.json` records
the fetched source renditions. Paths in both files are relative to this folder.
`crops.json` preserves the manually traced contours; `prepare.py` rebuilds the
PNG files and manifest using Pillow.

Every selected asset has a dated `review` covering its source identification,
orientation and crop. The main collection also records the reviewed image hash;
changing those pixels requires a new visual review. Review includes comparing
each bird against its preserved source and viewing the transparent PNG composited
on paper, so hidden RGB outside its alpha mask cannot be mistaken for visible
background. Fine source plants that overlap a bird remain where removing them
would require inventing anatomy.

```sh
python3 naturalist/artwork/prepare.py
python3 naturalist/artwork/verify.py
```

The six supplemental species live in `additions/`. Rebuild them with
`python3 naturalist/artwork/additions/prepare_additions.py` first when their
recipes change. The main builder appends `additions/manifest.json` and rejects
duplicate IDs. Its paths are relative to this artwork folder.

## Sources and attribution

| Species | Historical work / artist | Source |
| --- | --- | --- |
| House Finch | John Cassin, *Illustrations of the birds of California…*, plate 13 (1862); George G. White, William E. Hitchcock, John T. Bowen | [Biodiversity Heritage Library](https://www.biodiversitylibrary.org/page/27214159) |
| Cedar Waxwing | Louis Agassiz Fuertes, *The Burgess Bird Book for Children* (1919) | [Source and rights](https://commons.wikimedia.org/wiki/File:Dandy_the_Cedar_Waxwing.jpg) |
| Black-capped Chickadee | Louis Agassiz Fuertes, *The Burgess Bird Book for Children* (1919) | [Biodiversity Heritage Library](https://www.biodiversitylibrary.org/page/18025058) |
| European Starling | John Gould and Henry Constantine Richter, *The Birds of Asia* (1867–1872) | [Source and rights](https://commons.wikimedia.org/wiki/File:SturnusVulgarisGould.jpg) |
| American Robin | Heinrich von Kittlitz, *Kupfertafeln zur Naturgeschichte der Vögel* (1832) | [Source and rights](https://commons.wikimedia.org/wiki/File:Turdus_migratorius_1832.jpg) |
| Rock Pigeon | John Gerrard Keulemans, *Onze vogels in huis en tuin* (1873) | [Source and rights](https://commons.wikimedia.org/wiki/File:Columba_livia_1873.jpg) |
| Red-breasted Nuthatch | Ernest Thompson Seton, *Bird-life*, plate LXXI (1900) | [Biodiversity Heritage Library / public-domain record](https://commons.wikimedia.org/wiki/File:Bird-life_(Plate_LXXI)_BHL7856002.jpg) |
| Northern Flicker | Louis Agassiz Fuertes, *The Burgess Bird Book for Children* (1919) | [Source and rights](https://commons.wikimedia.org/wiki/File:Yellow_Wing_the_Flicker.jpg) |
| American Goldfinch | Louis Agassiz Fuertes, *The Burgess Bird Book for Children* (1919) | [Source and rights](https://commons.wikimedia.org/wiki/File:Chicoree_the_Goldfinch.jpg) |
| American Crow | John James Audubon, *The Birds of America*, plate 156 (1827–1838) | [University of Pittsburgh reproduction / rights](https://commons.wikimedia.org/wiki/File:156_American_Crow.jpg) |
| Evening Grosbeak | Allan Brooks, *The birds of California*, plate 15 (1923); BHL / Smithsonian Libraries scan | [Source and CC BY 2.0 scan license](https://commons.wikimedia.org/wiki/File:The_birds_of_California_(Plate_15)_(7699536850).jpg) |
| Killdeer | Ernest Thompson Seton, *Bird-life*, plate XI (1900) | [Biodiversity Heritage Library / public-domain record](https://commons.wikimedia.org/wiki/File:Bird-life_(Plate_XI)_BHL7855744.jpg) |
| Lesser Goldfinch | Allan Brooks, *The birds of California*, plate 18 (1923); BHL / Smithsonian Libraries scan | [Source and CC BY 2.0 scan license](https://commons.wikimedia.org/wiki/File:The_birds_of_California_(Plate_18)_(7699539986).jpg) |
| Rufous Hummingbird | John Gould and Henry Constantine Richter, *A monograph of the Trochilidae*, volume 3 (1861) | [Source and rights](https://commons.wikimedia.org/wiki/File:MonographTrochi3Goul_0092.jpg) |
| Eurasian Collared-Dove | John Gerrard Keulemans, *Scientific results of the second Yarkand Mission. Aves* (1891) | [Source and rights](https://commons.wikimedia.org/wiki/File:TurturStoliczkaeKeulemans.jpg) |
| Downy Woodpecker | Ernest Thompson Seton, *Bird-life*, plate XXIV (1900) | [Source and rights](https://commons.wikimedia.org/wiki/File:Bird-life_(Plate_XXIV)_BHL7855802.jpg) |
| Western Tanager | Louis Agassiz Fuertes, *Birds of the Rockies*, plate V (1902) | [Source and rights](https://commons.wikimedia.org/wiki/File:Birds_of_the_Rockies_(Plate_V)_BHL6515153.jpg) |

The supplemental catalogue includes Canyon Wren, Song Sparrow, Mountain
Chickadee, Black-billed Magpie, Great Horned Owl and Great Blue Heron; its
`additions/README.md` and manifest retain individual source and rights links.

The additional Stebbins House Finch source (1910), Audubon nuthatch plate and
Frivaldszky collared dove scan (1838) are retained as source research but are
not selected. Their attribution and rights declarations are recorded in
`ingestion.json` or the linked source page.

## Rights and processing

All historical works were published before 1931 and are public domain in the
United States. The source records mark the scans public domain **except the
Evening Grosbeak and Lesser Goldfinch scans**, whose source uses [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/).
For those scans, credit Allan Brooks and the Biodiversity Heritage Library /
Smithsonian Libraries, link the source and license, and identify the crop and
alpha mask as changes; these details are in the manifest. The other source
pages record the relevant country-of-origin and artist information. The code
license does not replace these artwork-specific rights. Keep attribution
visible on the dashboard and retain this provenance when sharing the collection.

The exact downloaded scans are preserved unchanged under `sources/`. Some
large Wikimedia originals are represented by the publisher's advertised
1920/3840-pixel rendition; `original_image_url` points to the full original
when available. BHL sources are its full-page WebP renditions. None of those
source files is silently replaced by the cutouts.

The prepared images apply a manually traced alpha mask around a bird, crop
empty space, apply a documented rotation where needed, and resize to a maximum
1400 pixels. There is no automatic global
white removal, recoloring, generative fill, or reconstructed plumage. Small
source-colored edge remnants and original branches can remain. All cutouts
were visually checked individually against their sources. The original paper, plate captions, adjacent
species, and rectangular backgrounds are omitted from display variants.

## Coverage and curation

Coverage is a starter collection, not the entire BirdNET history. Exact species
without reviewed artwork remain explicitly missing; never substitute a similar
bird. The historical flicker shows the yellow-shafted form, not a verified local
subspecies. Flicker is rotated into an upright climbing pose; nuthatch remains
in a natural head-down climbing pose. The American Goldfinch source obscures
its feet behind a plant, so no feet have been reconstructed.

To extend the collection:

1. Verify the species and historical publication at a museum/library or
   Wikimedia source record, including its rights statement and artist/date.
2. Preserve the unmodified source rendition, source/rights URLs and checksum
   in `ingestion.json`.
3. Add a stable variant ID and contour recipe in `crops.json`. Contour
   coordinates refer to the entire source scaled proportionally to 600 pixels
   wide; several polygons can preserve fine legs and branches.
4. Run `prepare.py`, compare the individual cutout with its source at display
   scale, including feet, bill, tail, orientation and mixed-species plates.
   Record the review metadata and reviewed image hash in the crop recipe,
   rebuild, then run `verify.py` before using it.

Keep source URLs as references, not instructions. External scans or metadata
must never supply executable processing code.
