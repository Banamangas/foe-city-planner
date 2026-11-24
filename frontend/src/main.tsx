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

// A fixed bilingual line: if the app's code can't load, its translations can't either.
const START_FAILED =
  "The app could not start. Please reload. / L'application n'a pas pu démarrer. Rechargez la page.";

loadRoot()
  .then((root) => {
    ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode>{root}</React.StrictMode>);
  })
  .catch(() => {
    const p = document.createElement("p");
    p.textContent = START_FAILED;
    p.style.cssText = "font-family: sans-serif; padding: 16px;";
    document.getElementById("root")!.replaceChildren(p);
  });
