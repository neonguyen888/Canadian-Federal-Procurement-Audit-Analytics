# Building the dashboard in Tableau Public

The design is in `design/`: three pages at 1600 × 900, dark theme. This guide turns them into a Tableau Public workbook. `mockup.py` draws the design images from the same data, so the numbers in them are what the finished dashboard should show.

## 1. Data

Run `./run_pipeline.sh` first. It writes five files to `data/tableau/`:

| File | One row is | Used on |
|---|---|---|
| `awards.csv` | an award, with its flags and risk score | pages 1 and 3 |
| `value_bins.csv` | a commodity type and $1,000 of value | page 2 |
| `bunching_summary.csv` | a limit or placebo value and a group | page 2 cards |
| `bunching_by_department.csv` | a department and commodity type | page 2 |
| `headline.csv` | the whole analysis (one row) | cards and notes on every page |

In Tableau Public, connect to `awards.csv` as a text file, then add the other four as separate data sources. They do not need to be joined: each sheet uses one source.

`awards.csv` has no vendor names. Each vendor has a code (`V00042`), so a viewer can still see that several awards went to the same supplier.

## 2. Theme

Set these once under **Format > Workbook** and **Format > Dashboard**.

| Use | Colour |
|---|---|
| Page background | `#1F1F27` |
| Panels | `#2A2A33` |
| Left rail | `#16161C` |
| Main text, main series | `#F2F2F5` (text), `#C9C9D2` (marks) |
| Secondary text, axis labels | `#A3A3B0` |
| Context series, grey bars | `#5E5E6C` |
| Gridlines, panel borders | `#3A3A46` |
| Highlight: the one number or series that matters | `#FFE600` |
| Key-finding panel fill | `#32321F` |

Font: Tableau Book for text and Tableau Semibold for titles and numbers. Titles 15 px, subtitles 12 px, card numbers 28 px, axis labels 11 px.

Gridlines: horizontal only, `#3A3A46`, 1 px. No borders on marks, no shadows, no gradients.

## 3. Calculated fields (on `awards.csv`)

```
Flagged                 SUM([Is Flagged])
Flag rate               SUM([Is Flagged]) / COUNT([Award Reference])
Sole-sourced share      SUM(IF [Competition] = "Sole-sourced" THEN 1 ELSE 0 END) / COUNT([Award Reference])
Value flagged           SUM(IF [Is Flagged] = 1 THEN [Value At Award] END)
Two or more flags       SUM(IF [N Flags] >= 2 THEN 1 ELSE 0 END)
Change                  [Value Now] / [Value At Award] - 1
Is Q4                   [Fiscal Quarter] = "Q4"
Above average           [Flag rate] > WINDOW_AVG([Flag rate])        // for the department chart colour
```

For the cards' "on prior year" lines, use a table calculation on `Fiscal Year`: `ZN(SUM([x])) / LOOKUP(ZN(SUM([x])), -1) - 1`, and show the value for 2025-2026. Fiscal 2026-2027 is still open; exclude it from the sparklines with a filter.

## 4. Layout

Dashboard size: **fixed, 1600 × 900**. Build each page from one horizontal container: a 84 px rail on the left, the content on the right with 24 px padding.

```
+------+--------------------------------------------------------------------+
| rail | Title, page question                         filters, data date     |
|      | [card] [card] [card] [card] [card]           height 117 px          |
|      | [key finding 31%]  [main chart 69%]          height 288 px          |
|      | [chart] [chart] [chart]                      height 306 px          |
+------+--------------------------------------------------------------------+
```

The rail holds three **Navigation** buttons (Overview, Limits, Queue), a **Method** button that shows and hides a floating text container, and two **Download** buttons (PNG and PDF). Mark the current page with a 4 px yellow bar on the left of its button.

The cards: each is a sheet with the number as text (28 px, Semibold), the label above in 12 px secondary text, and a one-line note below. The sparkline is a second, small line sheet placed in the same container, axes and gridlines hidden, the last point as a yellow circle.

The key-finding panel is a text object, fill `#32321F`, with a 4 px yellow bar on its left edge. Write it as two short paragraphs and a "Where to start" or "What to review" line. Insert the numbers from `headline.csv` with dynamic text (`<SUM(Amended Past Limit)>`) so the text updates when the data does.

## 5. Page 1: Overview

Filters on the top right: Fiscal Year, Department, Commodity. Apply them to all sheets on the page that use `awards.csv`.

| Sheet | Columns | Rows | Marks and colour |
|---|---|---|---|
| Cards (five) | | | Awards analysed `CNT(Award Reference)`; Value at award `SUM(Value At Award)`; Sole-sourced share; Flagged (number in yellow, yellow bar on the card); Value flagged |
| Value by quarter | Fiscal Year, Fiscal Quarter (discrete) | `SUM(Value At Award)` | Bars; colour by `Is Q4`: yellow for true, `#C9C9D2` for false |
| Flags by test | Measure Values: the five `T*` fields summed | Measure Names | Bars; Amendment growth yellow, the rest `#C9C9D2`; label "count  value" |
| Flag rate by department | `Flag rate` | Department, sorted by `Flagged`, top 8 | Bars; colour by `Above average`; reference line at the average, dashed, labelled "average" |
| Sole-sourced share by year | Fiscal Year | `Sole-sourced share` | Line with circles; highlight the highest year in yellow |

Chart titles say what the chart shows, for example "January to March is the biggest quarter". Put the numbers in titles with dynamic text where Tableau allows it.

## 6. Page 2: Limits

Filter: Commodity only, default Services. The bins and the trend come from the bunching estimate over all departments and years, so Fiscal Year and Department filters would make the trend wrong; leave them off this page.

| Sheet | Source | Build |
|---|---|---|
| Cards (five) | `bunching_summary.csv`, `headline.csv` | Observed in the last $5,000 and the trend's prediction; ratio for all awards; ratio for sole-sourced (yellow); placebo range; awards amended past the limit |
| Awards per $1,000 | `value_bins.csv` | Columns `Bin Start` (continuous, $20K to $60K); rows `Sole Sourced` and `Competed` stacked (`#C9C9D2` over `#5E5E6C`); dual axis with `Trend` as a dashed yellow line; reference band from $35K to $40K, yellow at 8% opacity; reference line at $40K, yellow |
| Sole-sourced share by value | `value_bins.csv` | `SUM(Sole Sourced) / SUM(Total)` by `Bin Start`, one line per commodity (solid services, dashed goods); reference lines at $25K and $40K |
| Departments against their own range | `bunching_by_department.csv`, Commodity Type = S, top 10 by Ratio | Gantt bar from `Placebo Lo` to `Placebo Hi` in `#3A3A46`; error bar `Ci Lo` to `Ci Hi`; circle at `Ratio`, yellow where `Ci Lo > Placebo Hi`; reference line at 1 |

Label the tallest bar on the histogram with an annotation: "10,245 awards between $39,000 and $40,000" (use the value from `value_bins.csv`).

## 7. Page 3: Queue

Filters: Department, Test (a parameter that filters on the chosen `T*` field = 1), Minimum score (a slider on `Risk Score`).

| Sheet | Build |
|---|---|
| Cards (five) | Flagged awards; two or more flags (yellow); value flagged; highest `Risk Score`; checks matching from `headline.csv` |
| Review queue | Text table filtered to `Is Flagged = 1`, sorted by `Risk Rank`, top 13. Columns: rank, Department, Vendor Code, Commodity, Value At Award, Value Now, Change (yellow text), T1 to T5 as small square marks (yellow when 1, outline when 0), Risk Score |
| Why it is flagged | Text sheet showing `Flag Details` for the selected award, split at " \| " into one line per test |
| Start here | Text object, same style as the key-finding panel |

Add a **Filter** dashboard action: selecting a row in the queue filters "Why it is flagged" to that award. Default to rank 1.

## 8. Method panel

A floating container, hidden by default, shown by the rail's Method button. Keep it short:

- Data: Proactive Publication of Contracts over $10,000, open.canada.ca, as of the date in `headline.csv`.
- Window: awards from 10 June 2019, when the $25,000 and $40,000 limits of the Government Contracts Regulations s.6(b) came into force.
- Five tests, each written twice (SQL and pandas) and compared award by award: `<Checks Matching>` of `<Checks Total>` checks agree.
- A flag marks an award for review. It is not a finding of wrongdoing.
- Full method and limits: [the report on GitHub](https://github.com/neonguyen888/Canadian-Federal-Procurement-Audit-Analytics/blob/main/reports/report.md).

## 9. Publish

Save to Tableau Public under a title that says what it is, for example "Federal procurement review: which contracts to check first". In the description, link [the GitHub repository](https://github.com/neonguyen888/Canadian-Federal-Procurement-Audit-Analytics). Tableau Public shows your name under the viz, so the dashboard itself carries no author line.

Before publishing, compare each card with `design/` and with `data/processed/results.json`. If a number differs, the filter or calculation is wrong, not the data.
