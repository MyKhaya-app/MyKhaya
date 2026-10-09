#!/usr/bin/env ruby
# frozen_string_literal: true

# Checks the committed shared schemes: one per environment for the app and
# one per environment for the widget extension.
#
#   MyKhaya-Dev          App,            Run Debug-Dev,  Archive Release-Dev
#   MyKhaya-Prod         App,            Run Debug-Prod, Archive Release-Prod
#   MyKhayaWidgets-Dev   MyKhayaWidgets, Run Debug-Dev,  Archive Release-Dev
#   MyKhayaWidgets-Prod  MyKhayaWidgets, Run Debug-Prod, Archive Release-Prod
#
# They are version-controlled source (ios/App/App.xcodeproj/xcshareddata/
# xcschemes/), so this script never regenerates them: a regenerated scheme
# would fall back to Xcode's default configurations and could build one
# environment's app with the other's settings. It removes stale shared
# schemes that are not in the list above (an old App/MyKhayaWidgets scheme
# left by a previous version of this script, or a removed target's scheme),
# because any leftover shared scheme also stops Xcode autogenerating schemes
# and confuses `xcodebuild -scheme`.

PROJECT_PATH = 'ios/App/App.xcodeproj'
SCHEMES_DIR = File.join(PROJECT_PATH, 'xcshareddata', 'xcschemes')
EXPECTED = {
  'MyKhaya-Dev' => %w[App Dev],
  'MyKhaya-Prod' => %w[App Prod],
  'MyKhayaWidgets-Dev' => %w[MyKhayaWidgets Dev],
  'MyKhayaWidgets-Prod' => %w[MyKhayaWidgets Prod]
}.freeze

abort "ERROR: #{SCHEMES_DIR} not found." unless File.directory?(SCHEMES_DIR)

Dir.glob(File.join(SCHEMES_DIR, '*.xcscheme')).each do |scheme_path|
  scheme_name = File.basename(scheme_path, '.xcscheme')
  next if EXPECTED.key?(scheme_name)

  File.delete(scheme_path)
  puts "== Removed stale shared scheme: #{scheme_name} =="
end

errors = []
EXPECTED.each do |scheme_name, (target_name, environment)|
  scheme_path = File.join(SCHEMES_DIR, "#{scheme_name}.xcscheme")
  unless File.exist?(scheme_path)
    errors << "#{scheme_name}: missing (restore it from git: #{scheme_path})"
    next
  end
  xml = File.read(scheme_path)
  configurations = xml.scan(/buildConfiguration = "([^"]+)"/).flatten.uniq.sort
  expected = ["Debug-#{environment}", "Release-#{environment}"]
  errors << "#{scheme_name}: uses #{configurations.inspect}, expected only #{expected.inspect}" unless configurations == expected
  errors << "#{scheme_name}: does not build the #{target_name} target" unless xml.include?("BlueprintName = \"#{target_name}\"")
  puts "== Checked shared scheme: #{scheme_name} (#{target_name}, #{expected.join(' / ')}) =="
end

abort "ERROR: shared scheme problems:\n  #{errors.join("\n  ")}" unless errors.empty?
