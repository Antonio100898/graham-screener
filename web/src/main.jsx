import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import IntrinsicValueTool from "./IntrinsicValueTool.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
    <IntrinsicValueTool />
  </React.StrictMode>,
);
