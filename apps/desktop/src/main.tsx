import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { getApiBaseUrl, getBridgeBaseUrl } from "./shared/api/config";
import "katex/dist/katex.min.css";

console.info(`[astra] API base url = ${getApiBaseUrl()}`);
console.info(`[astra] Bridge base url = ${getBridgeBaseUrl()}`);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
