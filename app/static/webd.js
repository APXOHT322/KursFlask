var doc_btn_ids = ["btn_report", "btn_missing_report", "btn_directive_bak", "btn_directive_mag"];

function search(e) {
    var caller_id = $("input[type=submit][clicked=true]").attr("id");
    if (doc_btn_ids.indexOf(caller_id) === -1) {
        e.preventDefault();
        jQuery.ajax({
            url: "/query",
            type: "POST",
            dataType: "html",
            data: jQuery("#webd_form").serialize(),
            success: function (response) {
                document.getElementById("webd_result").innerHTML = response;
            },
            error: function (response) {
                document.getElementById("webd_result").innerHTML = "Ошибка в запросе";
            }
        });
        e.preventDefault();
    }
}

function validate_file(e) {
    if (e.files[0].size > (1048576 * 10)) {
        $("#result_" + e.id + "_failure").text("Файлы размером более 10мб недопустимы!");
        $("#submit_" + e.id).attr("disabled", "disabled");
        $("#result_" + e.id + "_success").text("");
        $("#" + e.id).removeAttr("style");
        return;
    }
    if (e.files[0].type != "application/pdf") {
        $("#result_" + e.id + "_failure").text("Допустимы файлы только формата PDF!");
        $("#result_" + e.id + "_success").text("");
        $("#submit_" + e.id).attr("disabled", "disabled");
        $("#" + e.id).removeAttr("style");
        return;
    }
    $("#result_" + e.id + "_failure").text("");
    $("#result_" + e.id + "_success").text("");
    $("#submit_" + e.id).removeAttr("disabled");
    $("#" + e.id).removeAttr("style");
}

function showHideAdditional() {
    var wfa = document.getElementById("webd_form_additional").classList;
    wfa.toggle("hidden");
    document.getElementById("webd_form_show_additional").innerHTML =
        wfa.contains("hidden") ? "Больше &darr;" : "Меньше &uarr;";

    var wfa1 = document.getElementById("btn_missing_report").classList;
    wfa1.toggle("hidden");
}

function togglePrvYearInstruction() {
    var instr = document.getElementById("prv_year_instruction_content").classList;
    instr.toggle("hidden");
    document.getElementById("prv_year_instruction_button").innerHTML =
        instr.contains("hidden") ? "Инструкция по редактированию прошлых лет &darr;" :
            "Инструкция по редактированию прошлых лет &uarr;";
}

$(document).ready(function () {
    $("#js_check").remove();
    $("form input[type=submit]").click(function () {
        $("input[type=submit]", $(this).parents("form")).removeAttr("clicked");
        $(this).attr("clicked", "true");
    });
    $("#webd_form").submit(search);
});
