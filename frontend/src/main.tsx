import React from "react";
import ReactDOM from "react-dom/client";
import { pickRoot } from "./wizard/route";

// Each root loads only its own styles: the legacy dark stylesheet never reaches the wizard page.
async function loadRoot(): Promise<React.ReactElement> {
  if (pickRoot(window.location.pathname) === "advanced") {
    await import("./styles.css");
    const { App } = await import("./App");
    return <App />;
  }
  const { Wizard } = await import("./wizard/Wizard");
  return <Wizard />;
}

loadRoot().then((root) => {
  ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode>{root}</React.StrictMode>);
});
