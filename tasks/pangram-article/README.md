# pangram-article — the same design task, eight agents

add-teams asks one model the same question ten times and reads the
spread. This asks eight *different* agents one question once, so the
axis is who is answering: model, and how hard it was told to think.

The task is deliberately taste-shaped rather than test-shaped. There is
no build to pass and no schema to get right — there is a house style
measured off pangram.com, a fixed list of things the page must contain,
and 800-1200 words of prose to actually write. What separates the runs
is judgment, and judgment is the thing a benchmark usually can't show
you.

## Reading the results

Every run writes one file, `article/index.html`, self-contained. The
checks refuse a stub, refuse a page that references a local file that
isn't there (it has to survive alone in an iframe), and copy the page
next to the run's other artifacts.

So the side-by-side is:

    /artifacts/<instance>/<run-id>/page.html

for each of the eight, and eight iframes in a row is the whole
comparison. `diff.patch` in the same directory has the file too, if the
copy ever doesn't happen.

## The grid

Run ids carry the arm so nothing needs a join to read:

    s-low   s-high            sonnet at 2k and 16k thinking tokens
    o-low   o-high   o-max    opus at 2k, 16k, 32k
    h-low   h-high            haiku at 2k and 16k
    f-med                     fable at 8k — one, its ceiling is its own

Three same-model pairs differ only in reasoning, which is the only way
to see whether more thinking buys anything on a task with no right
answer.
