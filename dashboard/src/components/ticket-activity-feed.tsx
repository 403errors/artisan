"use client";

import { useState } from "react";
import { ActivityIcon, WrenchIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { CodeBlock } from "@/components/code-block";
import { GateBadge } from "@/components/gate-badge";
import { LiveStepIndicator } from "@/components/live-step-indicator";
import { useTicketEvents } from "@/hooks/use-ticket-events";
import { formatDateTime, relativeTime } from "@/lib/format";
import {
  groupByGate,
  groupToolCalls,
  isToolCallGroup,
  presentationFor,
  type EventTone,
  type ToolCallGroup,
} from "@/lib/ticket-events";
import { cn } from "@/lib/utils";
import type { TicketEvent } from "@/types/ticket-event";
import type { TicketDoc } from "@/types/ticket";

const TONE_CLASS: Record<EventTone, string> = {
  default: "bg-muted text-muted-foreground ring-border",
  active: "bg-status-active/10 text-status-active ring-status-active/25",
  ok: "bg-status-resolved/10 text-status-resolved ring-status-resolved/25",
  warn: "bg-status-review/10 text-status-review ring-status-review/25",
  error: "bg-status-urgent/10 text-status-urgent ring-status-urgent/25",
};

function stringifyPayload(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function EventRow({ event }: { event: TicketEvent }) {
  const { icon: Icon, tone } = presentationFor(event.type);
  const hasPayload =
    Boolean(event.detail) || event.args !== undefined || event.result !== undefined || Boolean(event.extra);
  const [open, setOpen] = useState(event.status === "error");

  return (
    <li className="relative flex gap-3 pl-8">
      <span
        className={cn(
          "absolute top-0 left-0 flex size-6 items-center justify-center rounded-full ring-1",
          TONE_CLASS[tone],
        )}
      >
        <Icon aria-hidden="true" className="size-3.5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm">{event.summary}</span>
          {event.toolName ? (
            <Badge variant="outline" className="font-mono text-[11px]">
              {event.toolName}
            </Badge>
          ) : null}
          <span className="ml-auto text-xs text-muted-foreground" title={formatDateTime(event.at)}>
            {relativeTime(event.at)}
          </span>
        </div>
        {hasPayload ? (
          <Collapsible open={open} onOpenChange={setOpen}>
            <CollapsibleTrigger className="w-fit text-left text-xs text-muted-foreground hover:text-foreground">
              {open ? "Hide details" : "Show details"}
            </CollapsibleTrigger>
            <CollapsibleContent className="overflow-hidden">
              <div className="flex flex-col gap-2 pt-1">
                {event.detail ? <p className="text-sm">{event.detail}</p> : null}
                {event.args !== undefined ? (
                  <CodeBlock label="args">{stringifyPayload(event.args)}</CodeBlock>
                ) : null}
                {event.result !== undefined ? (
                  <CodeBlock label="result">{stringifyPayload(event.result)}</CodeBlock>
                ) : null}
                {event.extra ? <CodeBlock label="extra">{stringifyPayload(event.extra)}</CodeBlock> : null}
              </div>
            </CollapsibleContent>
          </Collapsible>
        ) : null}
      </div>
    </li>
  );
}

function ToolCallGroupRow({ group }: { group: ToolCallGroup }) {
  const [open, setOpen] = useState(false);

  return (
    <li className="relative flex gap-3 pl-8">
      <span
        className={cn(
          "absolute top-0 left-0 flex size-6 items-center justify-center rounded-full ring-1",
          TONE_CLASS.default,
        )}
      >
        <WrenchIcon aria-hidden="true" className="size-3.5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="w-fit text-left text-sm text-muted-foreground hover:text-foreground">
            {open ? "Hide tool calls" : `Show tool calls (${group.events.length})`}
          </CollapsibleTrigger>
          <CollapsibleContent className="overflow-hidden">
            <ul className="relative flex flex-col gap-3 pt-2 before:absolute before:top-3 before:bottom-3 before:left-[11px] before:w-px before:bg-border">
              {group.events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </li>
  );
}

export function TicketActivityFeed({ ticket }: { ticket: TicketDoc }) {
  const { events, unavailable } = useTicketEvents(ticket.id);
  const groups = groupByGate(events);

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-1.5">
          <ActivityIcon aria-hidden="true" className="size-4" />
          Activity
        </CardTitle>
        {events.length > 0 ? (
          <span className="text-xs text-muted-foreground">{events.length} events</span>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {unavailable ? "Activity capture isn't available for this ticket yet." : "No recorded activity yet."}
          </p>
        ) : (
          groups.map((group, i) => (
            <div key={i} className="flex flex-col gap-2">
              {group.gate ? <GateBadge gate={group.gate} showLabel /> : null}
              <ul className="relative flex flex-col gap-3 before:absolute before:top-3 before:bottom-3 before:left-[11px] before:w-px before:bg-border">
                {groupToolCalls(group.events).map((item) =>
                  isToolCallGroup(item) ? (
                    <ToolCallGroupRow key={item.events[0].id} group={item} />
                  ) : (
                    <EventRow key={item.id} event={item} />
                  ),
                )}
              </ul>
            </div>
          ))
        )}
        <LiveStepIndicator
          status={ticket.status}
          currentStep={ticket.currentStep}
          updatedAt={ticket.updatedAt}
        />
      </CardContent>
    </Card>
  );
}
