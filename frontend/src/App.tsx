import { Routes, Route } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { ChatPage } from "@/pages/ChatPage";
import { SetupPage } from "@/pages/SetupPage";
import { ToolsPage } from "@/pages/ToolsPage";
import { ComputerUsePage } from "@/pages/ComputerUsePage";
import { ConnectionsPage } from "@/pages/ConnectionsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/computer-use" element={<ComputerUsePage />} />
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/tools" element={<ToolsPage />} />
      </Route>
    </Routes>
  );
}
