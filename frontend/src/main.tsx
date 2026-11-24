import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { pickRoot } from "./wizard/route";
import { Wizard } from "./wizard/Wizard";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{pickRoot(window.location.pathname) === "advanced" ? <App /> : <Wizard />}</React.StrictMode>,
);
