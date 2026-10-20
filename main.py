import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

URL = (
    "https://webgw.tse.ir/InstrumentProvider"
    "/api/v1/MarketWatch/MarketWatchCash/fa"
)
INTERVAL = 1

state = {
    "data": None,
    "updated_at": None,
    "error": None,
}


async def fetch_loop():
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"Accept": "application/json"},
    ) as client:
        while True:
            delay = INTERVAL

            try:
                response = await client.get(URL)

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    delay = max(
                        INTERVAL,
                        int(retry_after) if retry_after.isdigit() else 60,
                    )
                    state["error"] = (
                        f"محدودیت درخواست؛ تلاش مجدد پس از {delay} ثانیه"
                    )
                else:
                    response.raise_for_status()
                    data = response.json()

                    state.update(
                        data=data,
                        updated_at=datetime.now(timezone.utc).isoformat(),
                        error=None,
                    )

            except (httpx.HTTPError, ValueError):
                logging.exception("Market fetch failed")
                state["error"] = (
                    "دریافت اطلاعات ناموفق بود؛ آخرین داده حفظ شده است."
                )
                delay = 15

            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(fetch_loop())

    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan)


@app.get("/api/market")
async def market():
    return state


@app.get("/", response_class=HTMLResponse)
async def home():
    return """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>دیده‌بان بازار</title>

    <style>
        * { box-sizing: border-box; }

        body {
            font-family: Tahoma, sans-serif;
            background: #101827;
            color: #e5e7eb;
            margin: 0;
            padding: 24px;
        }

        h1 { font-size: 24px; }

        .card {
            background: #1f2937;
            padding: 20px;
            border-radius: 12px;
        }

        #status { color: #93c5fd; }
        #error { color: #fca5a5; }
        #count { color: #9ca3af; }

        input {
            width: 100%;
            padding: 12px;
            margin: 12px 0;
            border: 1px solid #475569;
            border-radius: 8px;
            background: #111827;
            color: white;
            font: inherit;
        }

        .table-container {
            overflow: auto;
            max-height: 70vh;
            border: 1px solid #374151;
            border-radius: 8px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            white-space: nowrap;
            font-size: 14px;
        }

        th, td {
            padding: 12px 16px;
            text-align: right;
            border-bottom: 1px solid #374151;
        }

        th {
            position: sticky;
            top: 0;
            background: #334155;
            z-index: 1;
        }

        tbody tr:nth-child(even) { background: #243244; }
        tbody tr:hover { background: #374151; }

        @media (max-width: 600px) {
            body { padding: 12px; }
            .card { padding: 12px; }
        }
    </style>
</head>

<body>
    <h1>دیده‌بان بازار</h1>

    <div class="card">
        <p id="status">در حال دریافت اطلاعات…</p>
        <p id="error" role="alert"></p>

        <input
            id="search"
            type="search"
            placeholder="جستجو در تمام ستون‌ها..."
            aria-label="جستجو در جدول"
        >

        <p id="count"></p>

        <div class="table-container">
            <table>
                <thead id="head"></thead>
                <tbody id="body"></tbody>
            </table>
        </div>
    </div>

    <script>
        let rows = [];
        let columns = [];
        let lastUpdatedAt = null;

        const numberFormat = new Intl.NumberFormat("fa-IR", {
            maximumFractionDigits: 10
        });

        // اولین آرایه موجود در پاسخ را پیدا می‌کند.
        function findRows(data) {
            if (Array.isArray(data)) return data;

            if (data && typeof data === "object") {
                const preferred = ["data", "result", "items", "records"];
                const keys = [
                    ...preferred.filter(key => key in data),
                    ...Object.keys(data).filter(
                        key => !preferred.includes(key)
                    )
                ];

                for (const key of keys) {
                    const found = findRows(data[key]);
                    if (found !== null) return found;
                }
            }

            return null;
        }

        function displayValue(value) {
            if (value === null || value === undefined) return "—";
            if (typeof value === "number") return numberFormat.format(value);
            if (typeof value === "boolean") return value ? "بله" : "خیر";
            if (typeof value === "object") return JSON.stringify(value);
            return String(value);
        }

        function renderTable() {
            const query = document.getElementById("search")
                .value.trim().toLocaleLowerCase();

            const filtered = rows.filter(row =>
                columns.some(key =>
                    displayValue(row[key])
                        .toLocaleLowerCase()
                        .includes(query)
                )
            );

            const head = document.getElementById("head");
            const body = document.getElementById("body");

            head.replaceChildren();
            body.replaceChildren();

            const headerRow = document.createElement("tr");

            for (const title of ["ردیف", ...columns]) {
                const th = document.createElement("th");
                th.textContent = title;
                headerRow.appendChild(th);
            }

            head.appendChild(headerRow);

            const fragment = document.createDocumentFragment();

            filtered.forEach((row, index) => {
                const tr = document.createElement("tr");
                const indexCell = document.createElement("td");

                indexCell.textContent = numberFormat.format(index + 1);
                tr.appendChild(indexCell);

                for (const key of columns) {
                    const td = document.createElement("td");
                    td.textContent = displayValue(row[key]);
                    tr.appendChild(td);
                }

                fragment.appendChild(tr);
            });

            if (!filtered.length) {
                const tr = document.createElement("tr");
                const td = document.createElement("td");

                td.colSpan = columns.length + 1;
                td.textContent = "داده‌ای برای نمایش وجود ندارد.";

                tr.appendChild(td);
                fragment.appendChild(tr);
            }

            body.appendChild(fragment);

            document.getElementById("count").textContent =
                "نمایش " + numberFormat.format(filtered.length) +
                " از " + numberFormat.format(rows.length) + " ردیف";
        }

        async function refresh() {
            try {
                const response = await fetch("/api/market", {
                    cache: "no-store"
                });

                if (!response.ok) {
                    throw new Error("Server error");
                }

                const result = await response.json();
                const messages = result.error ? [result.error] : [];

                document.getElementById("status").textContent =
                    result.updated_at
                        ? "آخرین دریافت موفق: " +
                          new Date(result.updated_at).toLocaleString("fa-IR")
                        : "در انتظار اولین دریافت موفق…";

                if (
                    result.data !== null &&
                    result.updated_at !== lastUpdatedAt
                ) {
                    const extracted = findRows(result.data);

                    if (extracted === null) {
                        messages.push(
                            "آرایه‌ای در پاسخ پیدا نشد؛ ساختار پاسخ باید بررسی شود."
                        );
                    } else {
                        rows = extracted.map(item =>
                            item !== null &&
                            typeof item === "object" &&
                            !Array.isArray(item)
                                ? item
                                : { value: item }
                        );

                        columns = [
                            ...new Set(rows.flatMap(row => Object.keys(row)))
                        ];

                        lastUpdatedAt = result.updated_at;
                        renderTable();
                    }
                }

                document.getElementById("error").textContent =
                    messages.join(" — ");

            } catch (error) {
                document.getElementById("error").textContent =
                    "ارتباط با سرور برقرار نشد؛ آخرین داده حفظ شده است.";
            } finally {
                setTimeout(refresh, 5000);
            }
        }

        document.getElementById("search")
            .addEventListener("input", renderTable);

        renderTable();
        refresh();
    </script>
</body>
</html>
"""
