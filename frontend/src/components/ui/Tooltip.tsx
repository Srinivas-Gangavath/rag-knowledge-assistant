import React from "react";
import MuiTooltip, { type TooltipProps as MuiTooltipProps } from "@mui/material/Tooltip";

export interface TooltipProps extends Omit<MuiTooltipProps, "title"> {
  title: React.ReactNode;
  children: React.ReactElement;
}

export function Tooltip({ title, children, placement = "top", ...props }: TooltipProps) {
  if (!title) return children;

  return (
    <MuiTooltip
      title={title}
      placement={placement}
      arrow
      slotProps={{
        tooltip: {
          className:
            "!bg-slate-900 !text-slate-100 !text-xs !font-medium !rounded-md !px-2.5 !py-1 !shadow-lg",
        },
        arrow: {
          className: "!text-slate-900",
        },
      }}
      {...props}
    >
      {children}
    </MuiTooltip>
  );
}
