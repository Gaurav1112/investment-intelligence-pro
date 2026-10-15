import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  /** Sort key: decimal strings are compared exactly (no float parsing), plain strings lexically. */
  sortValue?: (row: T) => string | number | null;
  numeric?: boolean;
  render: (row: T) => ReactNode;
}

type Dir = "ascending" | "descending";

/** Compare decimal strings exactly, without converting to floats. */
export function compareDecimal(a: string, b: string): number {
  const norm = (s: string) => {
    const neg = s.startsWith("-");
    const [i = "0", f = ""] = s.replace("-", "").split(".");
    return { neg, i: i.replace(/^0+(?=\d)/, ""), f };
  };
  const x = norm(a);
  const y = norm(b);
  if (x.neg !== y.neg) return x.neg ? -1 : 1;
  const sign = x.neg ? -1 : 1;
  if (x.i.length !== y.i.length) return sign * (x.i.length - y.i.length);
  if (x.i !== y.i) return sign * (x.i < y.i ? -1 : 1);
  const len = Math.max(x.f.length, y.f.length);
  const fx = x.f.padEnd(len, "0");
  const fy = y.f.padEnd(len, "0");
  return fx === fy ? 0 : sign * (fx < fy ? -1 : 1);
}

const DECIMAL = /^-?\d+(\.\d+)?$/;

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  caption,
  initialSort,
  onRowOpen,
}: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  caption: string;
  initialSort?: { key: string; dir: Dir };
  onRowOpen?: (row: T) => void;
}) {
  const [sort, setSort] = useState<{ key: string; dir: Dir } | null>(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    const out = [...rows].sort((ra, rb) => {
      const a = get(ra);
      const b = get(rb);
      if (a === null && b === null) return 0;
      if (a === null) return 1; // missing values always last, never treated as zero
      if (b === null) return -1;
      let c: number;
      if (typeof a === "string" && typeof b === "string" && DECIMAL.test(a) && DECIMAL.test(b)) c = compareDecimal(a, b);
      else if (typeof a === "number" && typeof b === "number") c = a - b;
      else c = String(a).localeCompare(String(b));
      if (c === 0) c = rowKey(ra).localeCompare(rowKey(rb)); // deterministic tiebreak
      return sort.dir === "ascending" ? c : -c;
    });
    return out;
  }, [rows, columns, sort, rowKey]);

  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              return (
                <th
                  key={c.key}
                  scope="col"
                  className={c.numeric ? "num" : undefined}
                  aria-sort={active ? sort?.dir : c.sortValue ? "none" : undefined}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      className="th-sort"
                      onClick={() =>
                        setSort({
                          key: c.key,
                          dir: active && sort?.dir === "ascending" ? "descending" : "ascending",
                        })
                      }
                    >
                      {c.header}
                      <span aria-hidden="true">{active ? (sort?.dir === "ascending" ? " ▲" : " ▼") : " ↕"}</span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={rowKey(r)}
              tabIndex={onRowOpen ? 0 : undefined}
              onKeyDown={(e) => {
                if (onRowOpen && e.key === "Enter" && e.target === e.currentTarget) onRowOpen(r);
              }}
            >
              {columns.map((c) => (
                <td key={c.key} className={c.numeric ? "num" : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
