/** Static export only: no server, no image optimizer, nothing Vercel-specific. */
const nextConfig = {
  output: 'export',
  trailingSlash: true,
  images: {
    loader: 'custom',
    loaderFile: './lib/image-loader.ts',
    // Match the widths site/tools/build_images.py writes, so srcset has no duplicates.
    deviceSizes: [480, 768, 1080, 1440, 1920],
    imageSizes: [240, 360],
  },
  poweredByHeader: false,
};
export default nextConfig;
