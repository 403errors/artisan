"use client";

import { useState } from "react";
import { CheckIcon, ChevronDownIcon, CopyIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

const COLLAPSE_AFTER_LINES = 12;

function diffLineClass(line: string): string | undefined {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-muted-foreground";
  if (line.startsWith("+")) return "text-status-resolved";
  if (line.startsWith("-")) return "text-status-urgent";
  if (line.startsWith("@@")) return "text-status-review";
  return undefined;
}

function Lines({ lines, variant }: { lines: string[]; variant: "plain" | "diff" }) {
  return (
    <>
      {lines.map((line, i) => (
        <span key={i} className={cn("block", variant === "diff" ? diffLineClass(line) : undefined)}>
          {line.length === 0 ? " " : line}
        </span>
      ))}
    </>
  );
}

export function CodeBlock({
  children,
  label,
  variant = "plain",
  className,
}: {
  children: string;
  label?: string;
  variant?: "plain" | "diff";
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  const lines = children.split("\n");
  const collapsible = lines.length > COLLAPSE_AFTER_LINES;
  const head = collapsible ? lines.slice(0, COLLAPSE_AFTER_LINES) : lines;
  const tail = collapsible ? lines.slice(COLLAPSE_AFTER_LINES) : [];

  async function copy() {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className={cn("rounded-md bg-muted/50 ring-1 ring-border", className)}>
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        {label ? (
          <span className="text-xs font-medium text-muted-foreground">{label}</span>
        ) : (
          <span />
        )}
        <Button variant="ghost" size="icon-xs" onClick={copy} aria-label="Copy to clipboard">
          {copied ? <CheckIcon /> : <CopyIcon />}
        </Button>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed whitespace-pre">
        <Lines lines={head} variant={variant} />
      </pre>
      {collapsible ? (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleContent className="overflow-hidden data-[starting-style]:h-0 data-[ending-style]:h-0">
            <pre className="max-h-72 overflow-y-auto border-t border-border p-3 font-mono text-xs leading-relaxed whitespace-pre">
              <Lines lines={tail} variant={variant} />
            </pre>
          </CollapsibleContent>
          <CollapsibleTrigger className="flex w-full items-center justify-center gap-1 border-t border-border py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground">
            <ChevronDownIcon
              aria-hidden="true"
              className={cn("size-3.5 transition-transform", open && "rotate-180")}
            />
            {open ? "Collapse" : `Show ${tail.length} more lines`}
          </CollapsibleTrigger>
        </Collapsible>
      ) : null}
    </div>
  );
}
