import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./plant.css";
import PlantApp from "./PlantApp";

createRoot(document.getElementById("root")!).render(<StrictMode><PlantApp /></StrictMode>);
