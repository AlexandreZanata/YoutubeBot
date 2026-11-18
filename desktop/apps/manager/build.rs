fn main() {
    // `fluent` follows `Palette.color-scheme`, which the window switches at runtime.
    slint_build::compile_with_config(
        "ui/app.slint",
        slint_build::CompilerConfiguration::new().with_style("fluent".into()),
    )
    .expect("the manager UI must compile");
}
