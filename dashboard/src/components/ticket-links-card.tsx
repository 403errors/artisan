import { CircleDotIcon, GitPullRequestArrowIcon, SquareKanbanIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ResourceLink } from "@/components/resource-link";
import { githubIssueUrl, jiraTicketUrl } from "@/lib/config";
import type { TicketDoc } from "@/types/ticket";

export function TicketLinksCard({ ticket }: { ticket: TicketDoc }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Links</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col items-start gap-2">
        <ResourceLink
          variant="chip"
          icon={CircleDotIcon}
          href={githubIssueUrl(ticket.githubRepo, ticket.githubIssueNumber)}
        >
          GitHub issue
        </ResourceLink>
        <ResourceLink variant="chip" icon={SquareKanbanIcon} href={jiraTicketUrl(ticket.jiraKey)}>
          Jira ticket
        </ResourceLink>
        {ticket.prUrl ? (
          <ResourceLink variant="chip" icon={GitPullRequestArrowIcon} href={ticket.prUrl}>
            Pull request
          </ResourceLink>
        ) : null}
      </CardContent>
    </Card>
  );
}
