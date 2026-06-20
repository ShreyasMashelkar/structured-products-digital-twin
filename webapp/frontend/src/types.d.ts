declare module "plotly.js-dist-min";
declare module "react-plotly.js/factory" {
  import { ComponentType } from "react";
  const createPlotlyComponent: (plotly: unknown) => ComponentType<any>;
  export default createPlotlyComponent;
}
