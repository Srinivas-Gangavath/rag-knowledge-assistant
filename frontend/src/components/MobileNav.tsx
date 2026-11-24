import Drawer from "@mui/material/Drawer";

import { Sidebar } from "./Sidebar";
import type { AppView } from "../types";

type MobileNavProps = {
  open: boolean;
  onClose: () => void;
  currentView: AppView;
  onNavigate: (view: AppView) => void;
};

export function MobileNav({
  open,
  onClose,
  currentView,
  onNavigate,
}: MobileNavProps) {
  return (
    <Drawer
      anchor="left"
      open={open}
      onClose={onClose}
      ModalProps={{ keepMounted: true }}
      aria-label="Navigation menu"
    >
      <Sidebar
        currentView={currentView}
        onNavigate={onNavigate}
        onNavigateAndClose={(view) => {
          onNavigate(view);
          onClose();
        }}
      />
    </Drawer>
  );
}
