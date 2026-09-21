module.exports = {
  preset: 'react-native',
  setupFiles: ['./jest.setup.js'],
  transformIgnorePatterns: [
    'node_modules/(?!(react-native|@react-native|@react-navigation|react-native-uuid|react-native-safe-area-context|react-native-gesture-handler|react-native-screens)/)',
  ],
};
