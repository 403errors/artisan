import { ExternalLinkIcon, type LucideIcon } from "lucide-react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const resourceLinkVariants = cva(
  "group/link inline-flex items-center gap-1.5 rounded-md text-muted-foreground transition-all outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 hover:text-foreground [&>svg]:pointer-events-none [&>svg]:size-3.5 [&>svg]:shrink-0",
  {
    variants: {
      variant: {
        chip: "border border-border px-2 py-0.5 text-xs hover:bg-muted hover:border-foreground/20",
        inline: "text-sm underline-offset-4 hover:underline",
        subtle: "text-xs hover:underline underline-offset-4",
      },
    },
    defaultVariants: { variant: "inline" },
  },
);

export function ResourceLink({
  href,
  icon: Icon,
  children,
  variant,
  className,
  onClick,
}: {
  href: string;
  icon?: LucideIcon;
  children: React.ReactNode;
  onClick?: React.MouseEventHandler<HTMLAnchorElement>;
} & VariantProps<typeof resourceLinkVariants> &
  Pick<React.ComponentProps<"a">, "className">) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={onClick}
      className={cn(resourceLinkVariants({ variant }), className)}
    >
      {Icon ? <Icon aria-hidden="true" /> : null}
      {children}
      <ExternalLinkIcon
        aria-hidden="true"
        className="size-3 -translate-x-0.5 opacity-0 transition-all group-hover/link:translate-x-0 group-hover/link:opacity-70"
      />
    </a>
  );
}
