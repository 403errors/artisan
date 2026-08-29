"use client";

import { useEffect, useState } from "react";
import { ClockIcon, CircleCheckBigIcon, Loader2Icon } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { toast } from "@/components/ui/toast";
import { useNow } from "@/hooks/use-now";
import {
  ACTION_META,
  availableActions,
  postTicketAction,
  type TicketActionKind,
} from "@/lib/ticket-actions";
import { currentGate } from "@/lib/ticket-derived";
import type { TicketDoc } from "@/types/ticket";

export function TicketActions({ ticket }: { ticket: TicketDoc }) {
  const now = useNow();
  const actions = availableActions(ticket, now);
  const [dialogKind, setDialogKind] = useState<TicketActionKind | null>(null);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<TicketActionKind | null>(null);
  const [queued, setQueued] = useState<{ kind: TicketActionKind; since: string } | null>(null);

  useEffect(() => {
    if (queued && ticket.updatedAt !== queued.since) setQueued(null);
  }, [ticket.updatedAt, queued]);

  if (actions.length === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
        <CircleCheckBigIcon aria-hidden="true" className="size-4" />
        No actions available
      </span>
    );
  }

  const dialogMeta = dialogKind ? ACTION_META[dialogKind] : null;

  async function confirmAction() {
    if (!dialogKind) return;
    const sinceUpdatedAt = ticket.updatedAt;
    setPending(dialogKind);

    const body: Record<string, unknown> = {};
    if (dialogKind === "retry") body.gate = currentGate(ticket);
    if (dialogKind === "escalate" && reason) body.reason = reason;

    const result = await postTicketAction(ticket.id, dialogKind, body);

    setPending(null);
    setDialogKind(null);
    setReason("");

    if (result.ok) {
      setQueued({ kind: dialogKind, since: sinceUpdatedAt });
      toast.add({
        title: `${ACTION_META[dialogKind].label} queued`,
        description: "Artisan will pick this up shortly.",
        type: "success",
      });
    } else {
      toast.add({
        title: `${ACTION_META[dialogKind].label} failed`,
        description: result.message,
        type: "error",
      });
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {actions.map(({ kind, enabled, disabledReason }) => {
        const meta = ACTION_META[kind];
        const Icon = meta.icon;
        const button = (
          <Button
            key={kind}
            variant={meta.variant}
            size="sm"
            disabled={!enabled || pending !== null}
            aria-label={`${meta.label} for ${ticket.jiraKey}`}
            onClick={() => setDialogKind(kind)}
          >
            {pending === kind ? <Loader2Icon className="animate-spin" /> : <Icon />}
            {meta.label}
          </Button>
        );
        if (!enabled && disabledReason) {
          return (
            <Tooltip key={kind}>
              <TooltipTrigger render={<span className="inline-flex" />}>{button}</TooltipTrigger>
              <TooltipContent>{disabledReason}</TooltipContent>
            </Tooltip>
          );
        }
        return button;
      })}

      {queued ? (
        <Badge variant="outline" className="gap-1">
          <ClockIcon aria-hidden="true" />
          Action queued
        </Badge>
      ) : null}

      <AlertDialog
        open={dialogKind !== null}
        onOpenChange={(open) => {
          if (!open && pending === null) {
            setDialogKind(null);
            setReason("");
          }
        }}
      >
        <AlertDialogContent>
          {dialogMeta ? (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>{dialogMeta.confirm.title}</AlertDialogTitle>
                <AlertDialogDescription>{dialogMeta.confirm.body}</AlertDialogDescription>
              </AlertDialogHeader>
              {dialogMeta.needsReason ? (
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  maxLength={500}
                  rows={3}
                  placeholder="Optional reason (recorded on the ticket)"
                  className="w-full rounded-md border border-input bg-transparent p-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                />
              ) : null}
              <AlertDialogFooter>
                <AlertDialogCancel disabled={pending !== null}>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  variant={dialogMeta.confirm.destructive ? "destructive" : "default"}
                  disabled={pending !== null}
                  onClick={confirmAction}
                >
                  {pending !== null ? <Loader2Icon className="animate-spin" /> : null}
                  {dialogMeta.confirm.confirmLabel}
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          ) : null}
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
