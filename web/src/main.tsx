import { Analytics } from "@vercel/analytics/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <App />
      {/* Inside the router so client-side navigations are counted as page
          views; outside it, only the first load would be. The component is a
          no-op off Vercel and in development, so it costs a local run nothing. */}
      <Analytics />
    </BrowserRouter>
  </StrictMode>,
);
