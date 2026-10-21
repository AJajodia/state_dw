# state_dw

Academic research project in Python, managed with uv.

## Directory structure

```text
data/
  raw/          Original input data; preserve unchanged
  derived/      Processed data generated from inputs
docs/           Project documentation
models/         Saved models and model artifacts
notebooks/      Exploratory analyses
notes/          Research notes
paper/          Manuscript and supporting materials
results/
  figs/         Generated figures
  tables/       Generated tables
src/            Reusable Python code
tests/          Tests
workflow/       Scripts that run analyses and pipelines
```

Use the project's uv environment to run Python (`uv run python ...`).
See `AGENTS.md` for project guidance.

## Download congressional data

Get an API key from https://api.congress.gov/sign-up/ and set the
`CONGRESS_API_KEY` environment variable. Then run:

```sh
uv run python workflow/pull_congress.py
```

If your key is stored in `.env` as `congresskey`, use
`uv run --env-file .env python workflow/pull_congress.py` instead.

This downloads **only the 119th Congress**, including all bill and resolution
types, detailed bill metadata (including sponsors), and every page of cosponsors.
For a small trial, add `--max-bills 2`; to restrict measure type, add
`--bill-type hr` or `--bill-type s`.

To randomly sample 1,000 measures without replacement:

```sh
uv run python workflow/pull_congress.py --sample-size 1000 --seed 42
```

Sampling first downloads the entire listing, deduplicates and sorts bill IDs,
then selects a uniform sample with the given seed. `sample.json` preserves the
selected records and population size. Details and cosponsors are downloaded
only for sampled measures. The default population includes resolutions.

Original JSON responses are saved under
`data/raw/congress/119/<UTC timestamp>/`: `bill_pages/` contains listing pages,
and `bills/<bill ID>/` contains `details.json` and `cosponsors/` pages.
Each run gets a new directory. `run.json` records the scope and start time;
`completed.json` is written only after successful completion. A failed run
retains its partial downloads; rerunning starts a fresh snapshot.

The script uses the Python standard library, spaces requests to respect the
API's documented 5,000 requests/hour limit, and retries rate limits and temporary
server/network failures. A full download can take several hours. Bill data can
change during a run, so a download is not an atomic snapshot of Congress.gov.
This retrieves metadata, not full bill texts or linked action histories.

API documentation: https://github.com/LibraryOfCongress/api.congress.gov

## Voteview DW-NOMINATE scores (119th Congress)

```sh
uv run python workflow/pull_voteview.py
```

Downloads the complete official `HS119_members.csv` to a new timestamped folder
under `data/raw/voteview/119/`, preserving all columns and missing scores.
`nominate_dim1` and `nominate_dim2` are the DW-NOMINATE coordinates; the
Nokken-Poole fields are distinct, Congress-specific estimates. The CSV includes
identifiers such as `bioguide_id` for linking to sponsors and cosponsors, as well
as House, Senate, and any President rows supplied by Voteview. Metadata records
the source, retrieval time, checksum, and chamber counts. Scores for the ongoing
Congress are provisional and may change as votes accumulate.

Source and field definitions: https://voteview.com/articles/data_help_members

## NeoBERT embeddings of bill summaries

The original sample download contains summary links, not summary text. First
fetch every summary page for those sampled measures (a CPU-only network task):

```sh
uv run --env-file .env python workflow/pull_bill_summaries.py \
  data/raw/congress/119/20261021T135506544068Z
```

This adds `summaries/` folders alongside bill details, including empty responses
when no summary exists. Completed folders are skipped on subsequent runs;
interrupted collections remain in timestamped partial folders for inspection.

For inference, use a Linux NVIDIA GPU allocation on HPC. The official NeoBERT
implementation depends on xFormers; its documented version requires an older
PyTorch stack than this project's Python 3.13. The following command uses a
separate Python 3.11 environment without changing the project's environment:

```sh
uv run --no-project --python 3.11 \
  --with-requirements workflow/requirements-neobert.txt \
  python workflow/embed_bill_summaries.py \
  data/raw/congress/119/20261021T135506544068Z \
  --device cuda --batch-size 4
```

Use a GPU node with compatible NVIDIA drivers/CUDA for PyTorch 2.5.1. A GPU with
16 GB VRAM is a reasonable starting allocation, not a measured requirement;
reduce `--batch-size` to 1 if memory is tight. Internet is needed for initial
package/model downloads, or prepare their caches before entering an offline job.
Transfer the congressional input folder (including fetched summaries) to HPC
along with the code. No scheduler-specific submission script is assumed.

The script selects one nonempty summary per measure: latest legislative action
date, then latest update date. It strips HTML, embeds with
`chandar-lab/NeoBERT`, and uses the final `[CLS]` representation following the
official example. Summaries longer than 4,096 tokens are truncated and flagged;
missing summaries are skipped rather than replaced with titles. This selection
uses the latest available text and is not appropriate for a historical
prediction task that requires only text available before a cutoff date.

Each run creates `data/derived/neobert/<UTC timestamp>/` containing:

- `embeddings.npy`: float32 matrix, one 768-dimensional vector per summary.
- `summaries.jsonl`: row-to-bill mapping, selected text, source file, text hash,
  dates, token counts, and truncation flags.
- `skipped.json`: measures with no nonempty summary.
- `completed.json`: model revision, package versions, parameters, and counts;
  written only on success.

Vectors are unnormalized base-model features, not a sentence-similarity model
fine-tuned for legislative text. Set `--revision <commit SHA>` to pin model code
and weights; the resolved model revision is also recorded. Loading this official
checkpoint uses Transformers' `trust_remote_code=True`.

At 250M parameters, NeoBERT's float32 weights alone occupy about 1 GB. CPU
inference on 1,000 summaries may be possible, but runtime depends strongly on
text lengths and hardware, and xFormers installation is simpler on Linux/CUDA.
No embedding generation has been run locally. For an explicitly approved CPU
run in a compatible environment, select `--device cpu --batch-size 1`.

Model documentation: https://huggingface.co/chandar-lab/NeoBERT
