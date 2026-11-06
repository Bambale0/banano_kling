import { miniAppBasePath } from './miniapp-build-profile.mjs'

/** @type {import('next').NextConfig} */
const exportMode = process.env.NEXT_EXPORT === '1'

const nextConfig = {
  images: {
    unoptimized: true,
  },
  output: exportMode ? 'export' : undefined,
  trailingSlash: exportMode,
  basePath: exportMode ? miniAppBasePath : '',
  assetPrefix: exportMode ? miniAppBasePath : undefined,
}

export default nextConfig
