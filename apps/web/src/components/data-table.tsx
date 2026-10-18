"use client";

import { type ColumnDef, type SortingState, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui";
import { cx } from "@/lib/format";

/** Server-driven table: sorting and pagination are applied by the API, not in the browser. */
export function DataTable<T>({
  data,
  columns,
  sorting,
  onSortingChange,
  page,
  pageSize,
  total,
  onPageChange,
  onRowClick,
  empty,
}: {
  data: T[];
  columns: ColumnDef<T, any>[];
  sorting?: SortingState;
  onSortingChange?: (s: SortingState) => void;
  page?: number;
  pageSize?: number;
  total?: number;
  onPageChange?: (p: number) => void;
  onRowClick?: (row: T) => void;
  empty?: React.ReactNode;
}) {
  const table = useReactTable({
    data,
    columns,
    manualSorting: true,
    manualPagination: true,
    state: { sorting: sorting ?? [] },
    onSortingChange: (u) => onSortingChange?.(typeof u === "function" ? u(sorting ?? []) : u),
    getCoreRowModel: getCoreRowModel(),
  });
  const pages = total && pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  return (
    <div>
      <div className="-mx-5 overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-line/70">
                {hg.headers.map((h) => {
                  const sortable = h.column.getCanSort();
                  const dir = h.column.getIsSorted();
                  return (
                    <th key={h.id} scope="col" className="label px-5 py-2.5 font-medium" aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : undefined}>
                      {sortable ? (
                        <button className="inline-flex items-center gap-1 hover:text-ink" onClick={h.column.getToggleSortingHandler()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {dir === "asc" ? <ArrowUp className="h-3 w-3" /> : dir === "desc" ? <ArrowDown className="h-3 w-3" /> : null}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-line/50">
            {table.getRowModel().rows.map((r) => (
              <tr
                key={r.id}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(r.original) : undefined}
                onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(r.original) : undefined}
                className={cx("transition-colors", onRowClick && "cursor-pointer hover:bg-raised/50")}
              >
                {r.getVisibleCells().map((c) => (
                  <td key={c.id} className="px-5 py-3 align-middle">
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data.length && (empty ?? <p className="py-8 text-center text-sm text-muted">No records match.</p>)}
      {onPageChange && total != null && (
        <div className="mt-4 flex items-center justify-between text-xs text-muted">
          <span>
            {total} record{total === 1 ? "" : "s"} · page {page} of {pages}
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" disabled={(page ?? 1) <= 1} onClick={() => onPageChange((page ?? 1) - 1)} icon={<ChevronLeft className="h-3.5 w-3.5" />}>
              Previous
            </Button>
            <Button size="sm" variant="ghost" disabled={(page ?? 1) >= pages} onClick={() => onPageChange((page ?? 1) + 1)}>
              Next <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
