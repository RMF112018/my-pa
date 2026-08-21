import type { Preview } from "@storybook/nextjs-vite";
import "../src/app/globals.css";

const preview: Preview = {
  globalTypes: {
    theme: { description: "Color theme", defaultValue: "light", toolbar: { icon: "paintbrush", items: ["light", "dark"] } },
    density: { description: "Interface density", defaultValue: "comfortable", toolbar: { icon: "sidebar", items: ["comfortable", "compact"] } },
  },
  decorators: [
    (Story, context) => {
      if (typeof document !== "undefined") {
        document.documentElement.dataset.theme = context.globals.theme;
        document.documentElement.dataset.density = context.globals.density;
      }
      return Story();
    },
  ],
  parameters: {
    a11y: {
      test: "error",
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    layout: "centered",
    viewport: {
      options: {
        mobile: { name: "Mobile 390", styles: { width: "390px", height: "844px" } },
        tablet: { name: "Tablet 768", styles: { width: "768px", height: "1024px" } },
        desktop: { name: "Desktop 1440", styles: { width: "1440px", height: "900px" } },
      },
    },
  },
};

export default preview;
